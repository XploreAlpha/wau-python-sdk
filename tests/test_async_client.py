"""AsyncClient + AsyncRetrier 单测 — 补覆盖率"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import ClientOptions, RetryConfig, CircuitConfig, AuthConfig, Role
from wau_sdk._retry import AsyncRetrier, Retrier, is_retryable
from wau_sdk._errors import (
    APIError,
    CircuitOpenError,
    MaxRetriesError,
    NotImplementedError as WauNotImplementedError,
)


@pytest.fixture
def mock_kernel() -> respx.MockRouter:
    with respx.mock(base_url="http://mock-kernel:18400") as router:
        yield router


# ============================
# AsyncClient 4 子服务
# ============================


@pytest.mark.asyncio
async def test_async_agents_list(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/registry/agents", params={"page": "1", "pageSize": "10"}).mock(
        return_value=httpx.Response(200, json={
            "agents": [{"name": "Whis", "status": "online", "trust": 0.85}],
            "total": 1, "page": 1, "pageSize": 10, "totalPages": 1,
        })
    )
    async with wau_sdk.AsyncClient("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        resp = await c.agents.list()
    assert len(resp.agents) == 1
    assert resp.agents[0].name == "Whis"


@pytest.mark.asyncio
async def test_async_agents_get(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/registry/agents/jarvis/status").mock(
        return_value=httpx.Response(200, json={
            "name": "jarvis", "status": "online", "trust": 0.9,
            "load": {"activeTasks": 0, "maxCapacity": 10, "cpuUsage": 0.1, "memoryUsage": 0.1},
            "circuit": "closed",
        })
    )
    async with wau_sdk.AsyncClient("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        status = await c.agents.get("jarvis")
    assert status.name == "jarvis"
    assert status.circuit == "closed"


@pytest.mark.asyncio
async def test_async_tasks_submit(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(200, json={
            "task_id": "t1", "status": "completed", "selected_agent": "Whis", "score": 0.5,
            "decision": {"selected_agent": "Whis", "score": 0.5, "decision_time_ms": 50},
        })
    )
    async with wau_sdk.AsyncClient("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        resp = await c.tasks.submit(wau_sdk.SubmitRequest(prompt="hello"))
    assert resp.status == "completed"


@pytest.mark.asyncio
async def test_async_kernel_info(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/kernel/info").mock(
        return_value=httpx.Response(200, json={
            "version": "v0.6.0", "startTime": "2026-06-14T00:00:00Z",
            "uptime": 60, "agentsCount": 3, "tasksCount": 5,
        })
    )
    async with wau_sdk.AsyncClient("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        info = await c.kernel.info()
    assert info.version == "v0.6.0"
    assert info.agentsCount == 3


@pytest.mark.asyncio
async def test_async_intent_recommend_raises_not_implemented() -> None:
    """IntentService gRPC stub 返 NotImplementedError"""
    async with wau_sdk.AsyncClient("http://mock-kernel:18400") as c:
        with pytest.raises(WauNotImplementedError):
            await c.intent.recommend("test", top_k=3)


# ============================
# AsyncRetrier
# ============================


@pytest.mark.asyncio
async def test_async_retrier_max_retries_zero() -> None:
    r = AsyncRetrier(RetryConfig(max_retries=0))
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        raise APIError(500, "server error")

    with pytest.raises(APIError):
        await r.do(op)
    assert calls == 1


@pytest.mark.asyncio
async def test_async_retrier_5xx_recovers() -> None:
    r = AsyncRetrier(RetryConfig(max_retries=3))
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise APIError(502, "bad gateway")
        return "ok"

    result = await r.do(op)
    assert result == "ok"


@pytest.mark.asyncio
async def test_async_retrier_4xx_no_retry() -> None:
    r = AsyncRetrier(RetryConfig(max_retries=3))
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        raise APIError(404, "not found")

    with pytest.raises(APIError):
        await r.do(op)
    assert calls == 1


# ============================
# CircuitOpenError + options validation
# ============================


def test_circuit_open_error_message() -> None:
    err = CircuitOpenError("custom message")
    assert "custom message" in str(err)
    err2 = CircuitOpenError()  # 默认 message
    assert "circuit breaker" in str(err2).lower()


def test_options_max_backoff_less_than_initial_raises() -> None:
    """max_backoff < initial_backoff 应抛 ValueError"""
    with pytest.raises(ValueError, match="max_backoff_ms"):
        RetryConfig(initial_backoff_ms=200, max_backoff_ms=100)


def test_options_jitter_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="jitter"):
        RetryConfig(jitter=1.5)
    with pytest.raises(ValueError, match="jitter"):
        RetryConfig(jitter=-0.1)


def test_auth_config_empty_secret_raises() -> None:
    with pytest.raises(ValueError, match="shared_secret"):
        AuthConfig(agent_name="x", shared_secret=b"")


def test_auth_config_empty_agent_name_raises() -> None:
    with pytest.raises(ValueError, match="agent_name"):
        AuthConfig(agent_name="", shared_secret=b"secret")


def test_circuit_state_default_closed() -> None:
    """未配 CircuitConfig(enabled=False) → circuit_state 返 closed"""
    c = wau_sdk.Client("http://localhost:18400", ClientOptions(
        circuit=CircuitConfig(enabled=False),
    ))
    assert c.circuit_state() == "closed"


def test_circuit_state_when_enabled() -> None:
    """配 CircuitConfig(enabled=True) → circuit_state 也是 closed(初始)"""
    c = wau_sdk.Client("http://localhost:18400", ClientOptions(
        circuit=CircuitConfig(enabled=True, failure_threshold=5),
    ))
    assert c.circuit_state() == "closed"


# ============================
# IntentService sync + CircuitOpen in retrier
# ============================


def test_intent_recommend_raises_not_implemented() -> None:
    c = wau_sdk.Client("http://localhost:18400")
    with pytest.raises(WauNotImplementedError):
        c.intent.recommend("test", top_k=3)


def test_retrier_circuit_open_does_not_retry() -> None:
    """CircuitOpenError 不应计入重试(已通过 is_retryable 过滤)"""
    # 模拟:Retrier 调 is_retryable(exc) 返 False(CircuitOpen) → 不重试
    assert is_retryable(CircuitOpenError()) is False


def test_sync_retrier_max_retries_exhausts() -> None:
    """MaxRetries 用尽抛 MaxRetriesError,包 last error"""
    r = Retrier(RetryConfig(max_retries=2))
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        raise APIError(503, "service unavailable")

    with pytest.raises(MaxRetriesError) as exc_info:
        r.do(op)
    assert isinstance(exc_info.value.last_error, APIError)
    assert exc_info.value.last_error.status_code == 503
    assert calls == 3  # 1 + 2 retries
