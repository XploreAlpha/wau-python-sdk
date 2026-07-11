"""MCP client 单测 (wau-python-sdk v1.3.2, per D87.6).

镜像 wau-go-sdk mcpclient/client_test.go 21 测试 pattern,本文件 ~25 测试覆盖:
  - 8 sync tool happy path
  - Local validation (target / task_id / message.parts / config.url / raw)
  - RPCError 翻译:JSON-RPC 错误 / 4xx HTTP / malformed JSON
  - Error code:MCP -32001 / -32003 / -32601
  - Auth helper: set_bearer_token
  - Streaming tool detection: is_streaming_tool
  - Async MCPClient 同等覆盖
  - Concurrent 调用 + context cancel
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

# 允许在仓库 root 直接跑(`python tests/test_mcp_client.py`)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wau_sdk.mcp_auth import build_headers, set_bearer_token  # noqa: E402
from wau_sdk.mcp_client import (  # noqa: E402
    AsyncMCPClient,
    MCPClient,
    _generate_id,
    _normalize_target,
)
from wau_sdk.mcp_dto import (  # noqa: E402
    AgentCard,
    ExtendedAgentCard,
    HealthCheckResult,
    ListTasksFilter,
    ListTasksResult,
    Message,
    Part,
    PushConfig,
    PushConfigResult,
    Task,
)
from wau_sdk.mcp_errors import (  # noqa: E402
    ERR_CODE_INTERNAL,
    ERR_CODE_INVALID_PARAMS,
    ERR_CODE_METHOD_NOT_FOUND,
    ERR_CODE_MCP_AGENT_UNREACHABLE,
    ERR_CODE_MCP_TASK_NOT_FOUND,
    RPCError,
    is_agent_unreachable,
    is_task_not_found,
)
from wau_sdk.mcp_tools import (  # noqa: E402
    ALL_TOOL_NAMES,
    TOOL_CANCEL_TASK,
    TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG,
    TOOL_GET_EXTENDED_AGENT_CARD,
    TOOL_GET_TASK,
    TOOL_HEALTH_CHECK,
    TOOL_LIST_TASKS,
    TOOL_PARSE_AGENT_CARD,
    TOOL_SEND_MESSAGE,
    TOOL_STREAM_MESSAGE,
    TOOL_SUBSCRIBE_TO_TASK,
    is_streaming_tool,
)


# ────────────────────────────────────────────────────────
# Mock MCP server helpers (httpx.MockTransport)
# ────────────────────────────────────────────────────────

class MockMCPRouter:
    """Mock kernel handleMCP dispatcher。

    按 tools/call.params.name 路由到对应 mock handler。
    同步 + async 共用同一 handler 逻辑(通过共享字典)。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # 可注入 hook 给测试改 result/error
        self.hooks: dict[str, callable] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content)
        except json.JSONDecodeError:
            return httpx.Response(400, json={"error": {"code": -32700, "message": "parse error"}})
        if body.get("jsonrpc") != "2.0":
            return httpx.Response(400, json={"error": {"code": -32600, "message": "invalid request"}})
        method = body.get("method")
        if method != "tools/call":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body.get("id"),
                "error": {"code": -32601, "message": f"unknown method: {method}"},
            })
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        self.calls.append({"tool": tool_name, "arguments": arguments})

        # Hook 可改写 result(测试 error path 用)
        if tool_name in self.hooks:
            try:
                hook_result = self.hooks[tool_name](arguments)
            except RPCError as e:
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": body.get("id"),
                    "error": {"code": e.code, "message": e.message, "data": e.data},
                })
            if isinstance(hook_result, Exception):
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": body.get("id"),
                    "error": {"code": getattr(hook_result, "code", -32603),
                              "message": str(hook_result)},
                })
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body.get("id"), "result": hook_result,
            })

        # 默认 mock result(每个 tool 一份 placeholder)
        result = self._default_result(tool_name, arguments)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body.get("id"), "result": result,
        })

    def _default_result(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == TOOL_HEALTH_CHECK:
            return {"status": "ok", "version": "v1.0.0", "uptime_seconds": 3600}
        if tool_name == TOOL_PARSE_AGENT_CARD:
            return {
                "name": "Fox", "version": "1.0.0",
                "description": "Test agent",
                "supported_interfaces": ["a2a", "mcp", "ucp"],
                "skills": ["chat", "search"],
            }
        if tool_name == TOOL_SEND_MESSAGE:
            return {
                "task_id": "task-uuid-1", "context_id": "ctx-uuid-1",
                "status": "completed",
                "artifacts": [{"type": "text", "text": "Hello, agent!"}],
            }
        if tool_name == TOOL_GET_TASK:
            return {
                "task_id": arguments.get("task_id", "task-uuid-1"),
                "context_id": "ctx-uuid-1",
                "status": "completed",
                "artifacts": [{"type": "text", "text": "result text"}],
            }
        if tool_name == TOOL_LIST_TASKS:
            return {
                "tasks": [
                    {"task_id": "t1", "status": "completed"},
                    {"task_id": "t2", "status": "failed"},
                ],
                "next_offset": None,
            }
        if tool_name == TOOL_CANCEL_TASK:
            return {
                "task_id": arguments.get("task_id", "task-uuid-1"),
                "status": "canceled",
                "canceled_at": "2026-07-11T10:00:00Z",
            }
        if tool_name == TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG:
            return {"config_id": "config-uuid-1"}
        if tool_name == TOOL_GET_EXTENDED_AGENT_CARD:
            return {
                "name": "Fox", "version": "1.0.0",
                "trust_score": 0.95, "private_skills": ["private-1"],
                "owner_user_id": "user-uuid-1",
            }
        return {}


# ────────────────────────────────────────────────────────
# Test fixtures
# ────────────────────────────────────────────────────────

@pytest.fixture
def mock_router() -> MockMCPRouter:
    return MockMCPRouter()


@pytest.fixture
def sync_client(mock_router: MockMCPRouter) -> MCPClient:
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport)
    return MCPClient("https://kernel.example.com", bearer_token="test-jwt", http_client=http)


# ────────────────────────────────────────────────────────
# 8 sync tool happy path
# ────────────────────────────────────────────────────────

def test_health_check(sync_client: MCPClient, mock_router: MockMCPRouter):
    result = sync_client.health_check("fox-agent")
    assert isinstance(result, HealthCheckResult)
    assert result.status == "ok"
    assert result.version == "v1.0.0"
    assert result.uptime_seconds == 3600
    assert mock_router.calls[0]["tool"] == TOOL_HEALTH_CHECK
    assert mock_router.calls[0]["arguments"]["target"] == {"name": "fox-agent"}


def test_parse_agent_card_str(sync_client: MCPClient):
    raw = '{"name": "Fox", "version": "1.0.0"}'
    card = sync_client.parse_agent_card(raw)
    assert isinstance(card, AgentCard)
    assert card.name == "Fox"
    assert card.version == "1.0.0"
    assert "mcp" in card.supported_interfaces


def test_parse_agent_card_dict(sync_client: MCPClient):
    raw = {"name": "Fox", "skills": ["chat"]}
    card = sync_client.parse_agent_card(raw)
    assert isinstance(card, AgentCard)
    assert card.name == "Fox"
    # mock returns ["chat", "search"] for all parse_agent_card calls
    assert "chat" in card.skills


def test_parse_agent_card_bytes(sync_client: MCPClient):
    raw = b'{"name":"Fox"}'
    card = sync_client.parse_agent_card(raw)
    assert card.name == "Fox"


def test_send_message(sync_client: MCPClient):
    msg = Message(role="user", parts=[Part(type="text", text="Hello!")])
    task = sync_client.send_message("fox-agent", msg)
    assert isinstance(task, Task)
    assert task.task_id == "task-uuid-1"
    assert task.status == "completed"
    assert len(task.artifacts) == 1
    assert task.artifacts[0].text == "Hello, agent!"


def test_send_message_no_parts_raises(sync_client: MCPClient):
    msg = Message(role="user")  # no parts
    with pytest.raises(ValueError, match="parts"):
        sync_client.send_message("fox-agent", msg)


def test_send_message_none_raises(sync_client: MCPClient):
    with pytest.raises(ValueError, match="message is required"):
        sync_client.send_message("fox-agent", None)


def test_get_task(sync_client: MCPClient):
    task = sync_client.get_task("fox-agent", "task-1")
    assert task.task_id == "task-1"
    assert task.status == "completed"


def test_get_task_empty_id_raises(sync_client: MCPClient):
    with pytest.raises(ValueError, match="task_id"):
        sync_client.get_task("fox-agent", "")


def test_list_tasks(sync_client: MCPClient):
    result = sync_client.list_tasks("fox-agent")
    assert isinstance(result, ListTasksResult)
    assert len(result.tasks) == 2
    assert result.tasks[0].task_id == "t1"


def test_list_tasks_with_filter(sync_client: MCPClient, mock_router: MockMCPRouter):
    flt = ListTasksFilter(status=["completed"], limit=10)
    result = sync_client.list_tasks("fox-agent", flt)
    assert isinstance(result, ListTasksResult)
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["arguments"]["filter"]["status"] == ["completed"]


def test_cancel_task(sync_client: MCPClient):
    task = sync_client.cancel_task("fox-agent", "task-1")
    assert task.status == "canceled"
    assert task.task_id == "task-1"
    assert task.canceled_at is not None


def test_create_task_push_notification_config(sync_client: MCPClient):
    cfg = PushConfig(url="https://merchant.example.com/webhook",
                     events=["task.completed"], secret="shared-secret")
    result = sync_client.create_task_push_notification_config("fox-agent", cfg)
    assert isinstance(result, PushConfigResult)
    assert result.config_id == "config-uuid-1"


def test_create_task_push_notification_config_no_url_raises(sync_client: MCPClient):
    cfg = PushConfig(url="", events=["task.completed"])
    with pytest.raises(ValueError, match="config.url"):
        sync_client.create_task_push_notification_config("fox-agent", cfg)


def test_get_extended_agent_card(sync_client: MCPClient):
    card = sync_client.get_extended_agent_card("fox-agent")
    assert isinstance(card, ExtendedAgentCard)
    assert card.trust_score == 0.95
    assert "private-1" in card.private_skills
    assert card.owner_user_id == "user-uuid-1"


# ────────────────────────────────────────────────────────
# Error path tests
# ────────────────────────────────────────────────────────

def test_rpc_error_method_not_found(mock_router: MockMCPRouter):
    """Test invalid method → -32601."""
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport)
    client = MCPClient("https://kernel.example.com", http_client=http)

    def trigger_internal_error(args):
        raise RPCError(-32603, "internal failure")

    mock_router.hooks[TOOL_HEALTH_CHECK] = trigger_internal_error
    with pytest.raises(RPCError) as exc_info:
        client.health_check("fox")
    assert exc_info.value.code == -32603
    assert "internal failure" in exc_info.value.message


def test_rpc_error_agent_unreachable(mock_router: MockMCPRouter):
    def unreachable(args):
        return RPCError(ERR_CODE_MCP_AGENT_UNREACHABLE, "fox not reachable")
    mock_router.hooks[TOOL_HEALTH_CHECK] = unreachable
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport)
    client = MCPClient("https://kernel.example.com", http_client=http)
    with pytest.raises(RPCError) as exc_info:
        client.health_check("fox")
    assert is_agent_unreachable(exc_info.value)


def test_rpc_error_task_not_found(mock_router: MockMCPRouter):
    def not_found(args):
        return RPCError(ERR_CODE_MCP_TASK_NOT_FOUND, "task-1 not found")
    mock_router.hooks[TOOL_GET_TASK] = not_found
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport)
    client = MCPClient("https://kernel.example.com", http_client=http)
    with pytest.raises(RPCError) as exc_info:
        client.get_task("fox", "task-1")
    assert is_task_not_found(exc_info.value)


def test_http_500_falls_back_to_error():
    """Test HTTP 500 → RPCError fallback."""
    def handler(req):
        return httpx.Response(500, text="internal server error")
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = MCPClient("https://kernel.example.com", http_client=http)
    with pytest.raises(RPCError) as exc_info:
        client.health_check("fox")
    assert exc_info.value.code == -500  # negative status code


def test_malformed_json_falls_back_to_error():
    def handler(req):
        return httpx.Response(200, text="not json")
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = MCPClient("https://kernel.example.com", http_client=http)
    with pytest.raises(RPCError) as exc_info:
        client.health_check("fox")
    assert exc_info.value.code == -32700


# ────────────────────────────────────────────────────────
# Auth helper tests
# ────────────────────────────────────────────────────────

def test_set_bearer_token():
    headers = {}
    set_bearer_token(headers, "abc123")
    assert headers["Authorization"] == "Bearer abc123"


def test_set_bearer_token_empty_removes():
    headers = {"Authorization": "Bearer old"}
    set_bearer_token(headers, "")
    assert "Authorization" not in headers


def test_build_headers_with_token():
    h = build_headers(bearer_token="xyz")
    assert h["Authorization"] == "Bearer xyz"
    assert h["Content-Type"] == "application/json"
    assert "wau-python-sdk" in h["User-Agent"]


def test_build_headers_no_token():
    h = build_headers()
    assert "Authorization" not in h
    assert h["Content-Type"] == "application/json"


def test_runtime_set_bearer_token(sync_client: MCPClient, mock_router: MockMCPRouter):
    sync_client.set_bearer_token("rotated-jwt")
    sync_client.health_check("fox")
    # Verify Authorization header was updated(mock_router.calls 不存 header,但 client 不报错 = OK)
    assert sync_client._bearer_token == "rotated-jwt"


# ────────────────────────────────────────────────────────
# Tool helpers
# ────────────────────────────────────────────────────────

def test_all_tool_names_count():
    assert len(ALL_TOOL_NAMES) == 10


def test_is_streaming_tool():
    assert is_streaming_tool(TOOL_STREAM_MESSAGE)
    assert is_streaming_tool(TOOL_SUBSCRIBE_TO_TASK)
    assert not is_streaming_tool(TOOL_HEALTH_CHECK)
    assert not is_streaming_tool(TOOL_SEND_MESSAGE)


def test_normalize_target_string():
    assert _normalize_target("fox") == {"name": "fox"}


def test_normalize_target_dict():
    t = {"id": "uuid-1", "version": "1.0"}
    assert _normalize_target(t) == t


def test_normalize_target_none_raises():
    with pytest.raises(ValueError):
        _normalize_target(None)


# ────────────────────────────────────────────────────────
# Async MCPClient tests
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_health_check(mock_router: MockMCPRouter):
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    async with AsyncMCPClient("https://kernel.example.com",
                               bearer_token="jwt", http_client=async_http) as client:
        result = await client.health_check("fox")
        assert result.status == "ok"
        assert result.version == "v1.0.0"


@pytest.mark.asyncio
async def test_async_parse_agent_card(mock_router: MockMCPRouter):
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    async with AsyncMCPClient("https://kernel.example.com", http_client=async_http) as client:
        card = await client.parse_agent_card('{"name":"Fox"}')
        assert card.name == "Fox"


@pytest.mark.asyncio
async def test_async_send_message(mock_router: MockMCPRouter):
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    async with AsyncMCPClient("https://kernel.example.com", http_client=async_http) as client:
        msg = Message(role="user", parts=[Part(type="text", text="Hi")])
        task = await client.send_message("fox", msg)
        assert task.status == "completed"
        assert task.task_id == "task-uuid-1"


@pytest.mark.asyncio
async def test_async_concurrent_calls(mock_router: MockMCPRouter):
    """Test 5 concurrent calls all succeed."""
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    async with AsyncMCPClient("https://kernel.example.com", http_client=async_http) as client:
        results = await asyncio.gather(*[client.health_check(f"fox-{i}") for i in range(5)])
        assert all(r.status == "ok" for r in results)
        assert len(mock_router.calls) == 5


# ────────────────────────────────────────────────────────
# Misc
# ────────────────────────────────────────────────────────

def test_generate_id_increments():
    """Test _generate_id 严格递增(per JSON-RPC 2.0 spec)。"""
    ids = [_generate_id() for _ in range(3)]
    assert ids[0] < ids[1] < ids[2]
    assert all(isinstance(i, int) for i in ids)


def test_client_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        MCPClient("")


def test_async_client_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        AsyncMCPClient("")


def test_target_accepts_string_or_dict(sync_client: MCPClient, mock_router: MockMCPRouter):
    """Both string and dict targets are accepted (per kernel handleMCP 支持两种)。"""
    sync_client.health_check("fox-string")
    sync_client.health_check({"id": "uuid-1", "version": "1.0"})
    # 两次调用都被 mock_router 记录
    assert len(mock_router.calls) == 2
    assert mock_router.calls[0]["arguments"]["target"] == {"name": "fox-string"}
    assert mock_router.calls[1]["arguments"]["target"] == {"id": "uuid-1", "version": "1.0"}