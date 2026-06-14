"""Circuit breaker — wau-circuit Go 版(154 行)的 Python 翻译

来源:[wau-circuit/breaker.go](https://github.com/XploreAlpha/wau-circuit/blob/main/breaker.go)
ADR-0003: 翻译到 3 SDK,行为 1:1 对齐(由"故障注入黄金测试"兜底)

状态机:
    Closed  ──(N failures)──>  Open
       ^                        │
       │                        │ recovery_timeout
       │                        ▼
       └─(1 success)───  HalfOpen
                           │
                           │ 1 failure
                           ▼
                         Open

Python 翻译要点:
- 状态用 enum.IntEnum(对应 Go iota)
- sync.RWMutex → threading.Lock(Python 单进程 GIL 下足够)
- map[agentID]state → dict[agentID, BreakerState](GIL 保护)
- 失败阈值 / 恢复超时:dataclass
- "wau-kernel" 作为单一 agentID(对齐 Go SDK)
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field

__all__ = [
    "CircuitState",
    "Breaker",
    "is_circuit_failure",
]


class CircuitState(enum.IntEnum):
    """熔断状态 — 对齐 wau-circuit.CircuitState (Go iota)"""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


# 默认值(对齐 wau-circuit DefaultFailureThreshold / DefaultRecoveryTimeout)
DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_TIMEOUT_S = 30.0


@dataclass
class _AgentState:
    """每个 agentID 内部状态(per-agent 计数器)"""
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    last_failure_at: float = 0.0


class Breaker:
    """熔断器 — wau-circuit.Breaker 的 Python 实现

    用法::

        cb = Breaker()  # 默认 5 failures / 30s 恢复
        if cb.is_open("agent-A"):
            raise CircuitOpenError()
        try:
            do_request()
            cb.record_success("agent-A")
        except (httpx.HTTP5xx, ConnectionError):
            cb.record_failure("agent-A")
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout_s: float = DEFAULT_RECOVERY_TIMEOUT_S,
    ) -> None:
        # 跟 Go 版一致:nil logger 自动 fallback 到 logging default
        # Go: if logger == nil { logger = slog.Default() }
        self._logger = logger if logger is not None else logging.getLogger("wau_sdk.circuit")
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._states: dict[str, _AgentState] = {}
        self._lock = threading.Lock()  # Go 用 RWMutex,Python 单进程 Lock 足够

    def _get_state_locked(self, agent_id: str) -> _AgentState:
        """在持锁状态下获取或创建 agent 状态"""
        s = self._states.get(agent_id)
        if s is None:
            s = _AgentState()
            self._states[agent_id] = s
        return s

    def get_state(self, agent_id: str) -> CircuitState:
        """获取 agent 当前状态(Closed / Open / HalfOpen)

        跟 Go 版语义:
        - Closed: 直接返
        - Open: 检查 time.Since(last_failure) > recovery_timeout → 转 HalfOpen
        - HalfOpen: 保持
        """
        with self._lock:
            s = self._get_state_locked(agent_id)
            if s.state == CircuitState.CLOSED:
                return CircuitState.CLOSED
            if s.state == CircuitState.OPEN:
                # Go: time.Since(lastFail) > recoveryTimeout → 转 HalfOpen
                if time.monotonic() - s.last_failure_at > self._recovery_timeout_s:
                    s.state = CircuitState.HALF_OPEN
                    return CircuitState.HALF_OPEN
                return CircuitState.OPEN
            # HALF_OPEN
            return CircuitState.HALF_OPEN

    def is_open(self, *agent_ids: str) -> bool:
        """变参:任意一个 agent Open 即 true(对齐 Go wau-circuit.IsOpen 变参)"""
        return any(self.get_state(aid) == CircuitState.OPEN for aid in agent_ids)

    def record_failure(self, agent_id: str) -> None:
        """记录一次失败 — 跟 Go 版逻辑 1:1

        Go 行为:
        - failures++ / lastFailure = now
        - 如果 state == HalfOpen → 转 Open(直接,不计数)
        - 如果 state == Closed && failures >= threshold → 转 Open
        """
        with self._lock:
            s = self._get_state_locked(agent_id)
            s.failures += 1
            s.last_failure_at = time.monotonic()

            # HalfOpen 失败 → 直接 Open(不计数)
            if s.state == CircuitState.HALF_OPEN:
                s.state = CircuitState.OPEN
                self._logger.warning(
                    "Circuit breaker re-opened from half-open",
                    extra={"agent": agent_id},
                )
                return

            if s.state == CircuitState.CLOSED and s.failures >= self._failure_threshold:
                s.state = CircuitState.OPEN
                self._logger.warning(
                    "Circuit breaker opened",
                    extra={"agent": agent_id, "failures": s.failures},
                )

    def record_success(self, agent_id: str) -> None:
        """记录一次成功 — 跟 Go 版逻辑 1:1

        Go 行为:
        - failures = 0
        - 如果 state == HalfOpen → 转 Closed
        """
        with self._lock:
            s = self._get_state_locked(agent_id)
            s.failures = 0
            if s.state == CircuitState.HALF_OPEN:
                s.state = CircuitState.CLOSED
                self._logger.info(
                    "Circuit breaker closed",
                    extra={"agent": agent_id},
                )

    def reset(self, agent_id: str) -> None:
        """重置 agent 状态(清 state + failures + lastFailure)"""
        with self._lock:
            self._states.pop(agent_id, None)


def is_circuit_failure(exc: BaseException) -> bool:
    """判断异常是否应计入熔断失败(对齐 wau-go-sdk is_circuit_failure)

    规则:
    - None: 不计
    - 5xx APIError: 计
    - 4xx APIError: 不计
    - 网络错 / Timeout: 计
    - CircuitOpenError 自身: 不计(避免雪崩)
    """
    if exc is None:
        return False
    # CircuitOpenError 不计(避免递归)
    from wau_sdk._errors import CircuitOpenError
    if isinstance(exc, CircuitOpenError):
        return False
    # 4xx 不计
    from wau_sdk._errors import APIError
    if isinstance(exc, APIError):
        return exc.status_code >= 500
    # 网络错 / Timeout / 其他: 计
    return True
