"""Transport 单测 — 4xx/5xx 翻译 + 鉴权 header 注入"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import AuthConfig, Role, ClientOptions, RetryConfig, CircuitConfig


@pytest.fixture
def mock_kernel() -> respx.MockRouter:
    with respx.mock(base_url="http://mock-kernel:18400") as router:
        yield router


def test_transport_get_health_2xx(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/health").mock(return_value=httpx.Response(200, json={
        "status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected"
    }))
    with wau_sdk.Client("http://mock-kernel:18400") as c:
        h = c.agents.health()
    assert h.status == "ok"
    assert h.version == "v0.6.0"


def test_transport_post_register_201(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.post("/registry/agents/register").mock(
        return_value=httpx.Response(201, json={"name": "test", "registered": True})
    )
    with wau_sdk.Client("http://mock-kernel:18400") as c:
        c.agents.register(wau_sdk.AgentRegisterRequest(name="test", url="http://t:18800"))


def test_transport_404_raises_not_found(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/registry/agents/ghost/status").mock(
        return_value=httpx.Response(404, json={"error": "agent not found", "code": "not_found"})
    )
    with wau_sdk.Client("http://mock-kernel:18400") as c:
        with pytest.raises(wau_sdk.NotFoundError) as exc_info:
            c.agents.get("ghost")
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "not_found"
    assert exc_info.value.message == "agent not found"


def test_transport_400_raises_bad_request(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(400, json={"error": "prompt is required", "code": "bad_request"})
    )
    with wau_sdk.Client("http://mock-kernel:18400") as c:
        with pytest.raises(wau_sdk.BadRequestError):
            c.tasks.submit(wau_sdk.SubmitRequest(prompt=""))


def test_transport_401_raises_unauthorized(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/kernel/info").mock(
        return_value=httpx.Response(401, json={"error": "invalid token", "code": "unauthorized"})
    )
    with wau_sdk.Client("http://mock-kernel:18400") as c:
        with pytest.raises(wau_sdk.UnauthorizedError):
            c.kernel.info()


def test_transport_5xx_passes_through_as_api_error(mock_kernel: respx.MockRouter) -> None:
    """5xx 没在 _STATUS_MAP,应返基类 APIError(不在 CircuitOpen 时)"""
    mock_kernel.get("/kernel/info").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        with pytest.raises(wau_sdk.APIError) as exc_info:
            c.kernel.info()
    assert exc_info.value.status_code == 500


def test_transport_invalid_json_response(mock_kernel: respx.MockRouter) -> None:
    """响应 body 不是 JSON → 抛 APIError(message 含 'invalid JSON')"""
    mock_kernel.get("/health").mock(return_value=httpx.Response(200, content=b"{not valid json"))
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        circuit=CircuitConfig(enabled=False),
    )) as c:
        with pytest.raises(wau_sdk.APIError) as exc_info:
            c.agents.health()
    assert "invalid JSON" in exc_info.value.message


def test_transport_sets_bearer_token_when_auth_enabled(mock_kernel: respx.MockRouter) -> None:
    """WithAuth 后,Authorization header 应含 Bearer JWT"""
    captured_auth: dict[str, str] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_auth["Authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected"})

    mock_kernel.get("/health").mock(side_effect=capture_handler)

    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        auth=AuthConfig(agent_name="test", shared_secret=b"test-secret-32-bytes-long-xxxxx", role=Role.TRUSTED_AGENT),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        c.agents.health()

    assert captured_auth["Authorization"].startswith("Bearer ")
    # JWT 格式: 3 段以 . 分隔
    jwt = captured_auth["Authorization"][len("Bearer "):]
    assert len(jwt.split(".")) == 3


def test_transport_no_auth_no_bearer_header(mock_kernel: respx.MockRouter) -> None:
    """无 WithAuth 时,Authorization header 不应设置"""
    captured_auth: dict[str, str] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_auth["Authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected"})

    mock_kernel.get("/health").mock(side_effect=capture_handler)

    with wau_sdk.Client("http://mock-kernel:18400") as c:
        c.agents.health()

    assert captured_auth["Authorization"] == ""


def test_transport_user_agent_header(mock_kernel: respx.MockRouter) -> None:
    """默认 User-Agent 应含 wau-python-sdk 版本"""
    captured_ua: dict[str, str] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_ua["User-Agent"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, json={"status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected"})

    mock_kernel.get("/health").mock(side_effect=capture_handler)

    with wau_sdk.Client("http://mock-kernel:18400") as c:
        c.agents.health()

    assert "wau-python-sdk" in captured_ua["User-Agent"]
    assert "0.6.0-preview.1" in captured_ua["User-Agent"]
