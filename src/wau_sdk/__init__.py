"""WAU Python SDK — 官方 Python 客户端,WAU-core-kernel 智能调度内核接入入口

v0.6.0 M3 W6 — 抽取自 wau-cli/internal/client/(2026-06-13)
扩展:
- typed errors (WauError 层级)
- 熔断(翻译 wau-circuit 154 行 → ~150 行 Python)
- 重试(tenacity,指数退避 + 抖动)
- HS256 鉴权(PyJWT)
- SubmitRequest 字段以 kernel 真相源为准

用法::

    import wau_sdk

    with wau_sdk.Client("http://localhost:18400") as c:
        resp = c.tasks.submit(wau_sdk.SubmitRequest(
            prompt="What is the capital of France?",
            timeout_ms=30000,
        ))
        print(resp.selected_agent, resp.response)

异步用法::

    import wau_sdk

    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        agents = await c.agents.list()
        print(agents)
"""

from wau_sdk._client import Client, AsyncClient
from wau_sdk._options import ClientOptions, RetryConfig, CircuitConfig, AuthConfig, Role
from wau_sdk._errors import (
    WauError,
    APIError,
    NotFoundError,
    UnauthorizedError,
    ForbiddenError,
    BadRequestError,
    ConflictError,
    CircuitOpenError,
    MaxRetriesError,
    NotImplementedError as WauNotImplementedError,  # avoid name clash with builtin
    HandshakeInsufficientTrustError,  # v0.8.0 M5-1 B.1
    HandshakeAgentNotFoundError,
    HandshakeTenantMismatchError,
    HandshakeRateLimitedError,
    HandshakeProtocolNotSupportedError,
    HandshakeSessionNotFoundError,
    HandshakeAgentNoEndpointError,
    HandshakeInvalidProtocolError,
    HandshakeInvalidRequestError,
)
from wau_sdk.types import (
    HealthResponse,
    KernelInfo,
    Agent,
    AgentListResponse,
    AgentRegisterRequest,
    AgentScore,
    AgentStatus,
    AgentLoad,
    PageOptions,
    PageResult,
    Task,
    SubmitRequest,
    SubmitResponse,
    DecisionInfo,
    Candidate,
    IntentDTO,
    HandshakeRequest,  # v0.8.0 M5-1 B.1
    HandshakeResponse,
    HandshakeSessionDetail,
    HandshakeStats,
)
# v0.8.0 M3-2B 新增
from wau_sdk.universe_labels import (
    LabelsValidationResult,
    RESERVED_UNIVERSE_LABEL_KEYS,
    is_reserved_label_key,
    validate_universe_labels,
    log_labels_validation,
)

__version__ = "0.6.0-preview.1"

__all__ = [
    # Client
    "Client",
    "AsyncClient",
    # Options
    "ClientOptions",
    "RetryConfig",
    "CircuitConfig",
    "AuthConfig",
    "Role",
    # Errors
    "WauError",
    "APIError",
    "NotFoundError",
    "UnauthorizedError",
    "ForbiddenError",
    "BadRequestError",
    "ConflictError",
    "CircuitOpenError",
    "MaxRetriesError",
    "WauNotImplementedError",
    # Types
    "HealthResponse",
    "KernelInfo",
    "Agent",
    "AgentListResponse",
    "AgentRegisterRequest",
    "AgentScore",
    "AgentStatus",
    "AgentLoad",
    "PageOptions",
    "PageResult",
    "Task",
    "SubmitRequest",
    "SubmitResponse",
    "DecisionInfo",
    "Candidate",
    "IntentDTO",
    # v0.8.0 M3-2B
    "LabelsValidationResult",
    "RESERVED_UNIVERSE_LABEL_KEYS",
    "is_reserved_label_key",
    "validate_universe_labels",
    "log_labels_validation",
    # v0.8.0 M5-1 B.1 — Handshake
    "HandshakeRequest",
    "HandshakeResponse",
    "HandshakeSessionDetail",
    "HandshakeStats",
    "HandshakeInsufficientTrustError",
    "HandshakeAgentNotFoundError",
    "HandshakeTenantMismatchError",
    "HandshakeRateLimitedError",
    "HandshakeProtocolNotSupportedError",
    "HandshakeSessionNotFoundError",
    "HandshakeAgentNoEndpointError",
    "HandshakeInvalidProtocolError",
    "HandshakeInvalidRequestError",
    "__version__",
]
