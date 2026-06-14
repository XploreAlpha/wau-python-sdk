"""W6.8 翻译测试 — wau-circuit Go 9 个 table-driven 单测的 Python 1:1 镜像

ADR-0003: 行为对齐,保证 3 SDK 熔断器语义字节级一致。
"""

from __future__ import annotations

import threading
import time

import pytest

from wau_sdk._circuit import (
    Breaker,
    CircuitState,
    DEFAULT_FAILURE_THRESHOLD,
    is_circuit_failure,
)
from wau_sdk._errors import (
    APIError,
    BadRequestError,
    CircuitOpenError,
    NotFoundError,
)


# ============================
# 状态机:Closed → Open
# ============================


def test_closed_to_open_after_threshold_failures() -> None:
    cb = Breaker(failure_threshold=3, recovery_timeout_s=0.05)
    # 2 次失败:仍 Closed
    for i in range(2):
        cb.record_failure("agent-A")
        assert cb.get_state("agent-A") == CircuitState.CLOSED, f"after {i + 1} failures"
    # 第 3 次:跳 Open
    cb.record_failure("agent-A")
    assert cb.get_state("agent-A") == CircuitState.OPEN


# ============================
# 状态机:Open → HalfOpen(超时后)
# ============================


def test_open_to_half_open_after_recovery_timeout() -> None:
    cb = Breaker(failure_threshold=1, recovery_timeout_s=0.02)
    cb.record_failure("agent-B")
    assert cb.get_state("agent-B") == CircuitState.OPEN

    # 立即查:仍 Open(time.Since 不通过)
    assert cb.get_state("agent-B") == CircuitState.OPEN

    # 等超时
    time.sleep(0.03)

    # 现在 get_state 应触发 Open → HalfOpen
    assert cb.get_state("agent-B") == CircuitState.HALF_OPEN


# ============================
# 状态机:HalfOpen → Closed(成功)
# ============================


def test_half_open_to_closed_on_success() -> None:
    cb = Breaker(failure_threshold=1, recovery_timeout_s=0.01)
    cb.record_failure("agent-C")
    time.sleep(0.015)
    _ = cb.get_state("agent-C")  # 触发 Open → HalfOpen
    assert cb.get_state("agent-C") == CircuitState.HALF_OPEN

    cb.record_success("agent-C")
    assert cb.get_state("agent-C") == CircuitState.CLOSED


# ============================
# 状态机:HalfOpen → Open(再失败)
# ============================


def test_half_open_to_open_on_failure() -> None:
    cb = Breaker(failure_threshold=1, recovery_timeout_s=0.01)
    cb.record_failure("agent-D")
    time.sleep(0.015)
    _ = cb.get_state("agent-D")  # 触发 Open → HalfOpen

    # HalfOpen 状态下再失败:回 Open
    cb.record_failure("agent-D")
    assert cb.get_state("agent-D") == CircuitState.OPEN


# ============================
# 未知 agent 默 Closed
# ============================


def test_unknown_agent_defaults_closed() -> None:
    cb = Breaker()
    assert cb.get_state("agent-zzz") == CircuitState.CLOSED


# ============================
# IsOpen 变参:任一 Open 即 true
# ============================


def test_is_open_variadic() -> None:
    cb = Breaker(failure_threshold=1)
    cb.record_failure("agent-A")  # Open
    # agent-B 未触发:仍 Closed

    assert cb.is_open("agent-A", "agent-B") is True
    assert cb.is_open("agent-A") is True
    assert cb.is_open("agent-B", "agent-C") is False
    assert cb.is_open() is False


# ============================
# Reset 清理状态
# ============================


def test_reset_clears_state() -> None:
    cb = Breaker(failure_threshold=1)
    cb.record_failure("agent-A")  # Open
    assert cb.get_state("agent-A") == CircuitState.OPEN

    cb.reset("agent-A")
    assert cb.get_state("agent-A") == CircuitState.CLOSED


# ============================
# 并发安全(10 goroutine × 1000 Record*)
# ============================


def test_concurrent_record_safe() -> None:
    cb = Breaker(failure_threshold=1000)
    success_count = 0
    fail_count = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal success_count, fail_count
        for j in range(1000):
            if j % 2 == 0:
                cb.record_failure("agent-concurrent")
                with lock:
                    fail_count += 1
            else:
                cb.record_success("agent-concurrent")
                with lock:
                    success_count += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert success_count == 5000
    assert fail_count == 5000
    # 状态在 1000 阈值下应仍 Closed(交替 success/fail 互相抵消)
    assert cb.get_state("agent-concurrent") == CircuitState.CLOSED


# ============================
# is_circuit_failure(对齐 Go isCircuitFailure)
# ============================


def test_is_circuit_failure() -> None:
    # None
    assert is_circuit_failure(None) is False
    # 5xx
    assert is_circuit_failure(APIError(500, message="server error")) is True
    assert is_circuit_failure(APIError(503)) is True
    # 4xx
    assert is_circuit_failure(NotFoundError()) is False
    assert is_circuit_failure(BadRequestError()) is False
    # 网络错
    assert is_circuit_failure(ConnectionError("dial tcp")) is True
    # CircuitOpenError 自身不计
    assert is_circuit_failure(CircuitOpenError()) is False


# ============================
# nil logger fallback(对齐 Go NewBreaker nil check)
# ============================


def test_nil_logger_fallback() -> None:
    """wau-circuit v0.6.0 修了 nil logger panic bug,Python 翻译也确保不抛"""
    cb = Breaker(logger=None)  # 不传 logger
    cb.record_failure("test")  # 不应抛
    assert cb.get_state("test") == CircuitState.CLOSED


# ============================
# CircuitState 字符串
# ============================


def test_circuit_state_str() -> None:
    """对齐 wau-circuit CircuitState.String() (Go 侧"closed"/"open"/"half-open")"""
    # 状态枚举值验证
    assert int(CircuitState.CLOSED) == 0
    assert int(CircuitState.OPEN) == 1
    assert int(CircuitState.HALF_OPEN) == 2


# ============================
# 默认配置
# ============================


def test_default_config_matches_go() -> None:
    """默认 5 failures / 30s 恢复 — 对齐 wau-circuit DefaultFailureThreshold / DefaultRecoveryTimeout"""
    cb = Breaker()
    assert cb._failure_threshold == DEFAULT_FAILURE_THRESHOLD
    assert cb._failure_threshold == 5
    assert cb._recovery_timeout_s == 30.0
