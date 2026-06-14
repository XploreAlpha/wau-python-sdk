"""配置 dataclass — 跟 wau-go-sdk options.go 字段 1:1 对应"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """RBAC 角色"""
    KERNEL_CORE = "kernel_core"
    TRUSTED_AGENT = "trusted_agent"
    EXTERNAL_AGENT = "external_agent"


@dataclass
class RetryConfig:
    """重试配置 — 指数退避 + 抖动(对齐 Go SDK RetryConfig)

    策略:max_retries=3 / initial=200ms / max=5s / jitter=0.2
    只对**幂等**请求自动重试;非幂等 POST 默认不重试
    """
    max_retries: int = 3
    initial_backoff_ms: int = 200
    max_backoff_ms: int = 5000
    jitter: float = 0.2
    retry_on: list[int] = field(default_factory=lambda: [500, 502, 503, 504, 429])

    def __post_init__(self) -> None:
        if self.max_backoff_ms < self.initial_backoff_ms:
            raise ValueError("max_backoff_ms must be >= initial_backoff_ms")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter must be in [0, 1]")


@dataclass
class CircuitConfig:
    """熔断配置(对齐 Go SDK CircuitConfig + wau-circuit)"""
    failure_threshold: int = 5
    open_timeout_ms: int = 30000
    half_open_max: int = 1
    enabled: bool = True


@dataclass
class AuthConfig:
    """HS256 Bearer 鉴权配置

    exp: 5 分钟(短;每次请求新签)
    jti: UUID v4 防重放
    """
    role: Role = Role.EXTERNAL_AGENT
    agent_name: str = ""
    shared_secret: bytes = b""

    def __post_init__(self) -> None:
        if not self.shared_secret:
            raise ValueError("shared_secret is required for HS256")
        if not self.agent_name:
            raise ValueError("agent_name is required")


@dataclass
class ClientOptions:
    """顶层 SDK 配置(对齐 Go SDK Options)"""
    timeout_ms: int = 30000
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit: CircuitConfig = field(default_factory=CircuitConfig)
    auth: AuthConfig | None = None
    user_agent: str = "wau-python-sdk/0.6.0-preview.1"
    transport: Any = None  # httpx.Client/AsyncClient 注入点(测试/代理)


def default_options() -> ClientOptions:
    """默认配置(Quickstart 用)"""
    return ClientOptions()


def with_timeout(options: ClientOptions, timeout_ms: int) -> ClientOptions:
    options.timeout_ms = timeout_ms
    return options


def with_retry_no(options: ClientOptions) -> ClientOptions:
    options.retry.max_retries = 0
    return options


def with_circuit_disabled(options: ClientOptions) -> ClientOptions:
    options.circuit.enabled = False
    return options


def with_auth(options: ClientOptions, auth: AuthConfig) -> ClientOptions:
    options.auth = auth
    return options
