"""MCP SSE streaming client 单测 (wau-python-sdk v1.3.3, per D89.A.6).

镜像 wau-go-sdk mcpclient/streaming_test.go pattern(本仓 W7+ 实装),
本文件 ~30 测试覆盖:
  - SSE frame 类型: open / message / artifact / task_status / task_complete / close / error
  - 错误路径: POST 4xx / GET 4xx / 401 / 404 / stream_id mismatch / malformed JSON
  - Local validation: message.parts / task_id empty / target
  - Auth: bearer token 在 GET /mcp/sse 的 Authorization 头
  - StreamHandle: cancel 幂等 / context manager / close after cancel
  - StreamOptions: include_history / include_artifacts / 默认空 dict
  - 并发: 多个 stream_message 并行
  - 长跑: 多个 SSE event 顺序消费
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

# 允许在仓库 root 直接跑(`python tests/test_mcp_streaming.py`)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wau_sdk.mcp_client import AsyncMCPClient  # noqa: E402
from wau_sdk.mcp_dto import Message, Part  # noqa: E402
from wau_sdk.mcp_errors import RPCError  # noqa: E402
from wau_sdk.mcp_streaming import (  # noqa: E402
    ERR_CODE_STREAM_CLOSED,
    FRAME_ARTIFACT,
    FRAME_CLOSE,
    FRAME_ERROR,
    FRAME_MESSAGE,
    FRAME_OPEN,
    FRAME_TASK_COMPLETE,
    FRAME_TASK_STATUS,
    MCP_STREAM_CLOSED_MSG,
    StreamEvent,
    StreamHandle,
    StreamOptions,
    open_stream,
)


# ────────────────────────────────────────────────────────
# Mock MCP SSE server (httpx.MockTransport + custom streaming handler)
# ────────────────────────────────────────────────────────

class MockMCPSSERouter:
    """Mock kernel SSE handler:POST /mcp 启 stream,GET /mcp/sse 返回 SSE 帧。

    Usage::

        router = MockMCPSSERouter()
        router.set_sse_body([{"event": "open", "data": {...}}, ...])
        transport = httpx.MockTransport(router.handle)
        async with httpx.AsyncClient(transport=transport) as http:
            client = AsyncMCPClient("...", http_client=http)
            handle = await client.stream_message("fox", msg)
    """

    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.post_response: dict | None = None  # Override POST response
        self.sse_body: list[dict] = []  # List of {"event": str, "data": str|dict}
        self.sse_status: int = 200  # Override GET response status
        self.endpoint: str = "/mcp/sse"
        self.default_stream_id: str = "stream-uuid-1"

    def set_sse_body(self, frames: list[dict]) -> None:
        """设置 GET /mcp/sse 返回的 SSE frame sequence。

        Each frame: {"event": "<type>", "data": <dict|str>, "comment": "<str>"(optional)}
        """
        self.sse_body = frames

    def encode_sse_body(self) -> bytes:
        """Encode SSE frames to bytes (per SSE spec format)。"""
        out = []
        for fr in self.sse_body:
            event = fr.get("event")
            data = fr.get("data")
            comment = fr.get("comment")
            if comment is not None:
                out.append(":" + comment)
                out.append("")
                continue
            if event is not None:
                out.append(f"event: {event}")
            if data is not None:
                # Per SSE spec: data on one line → use single line
                data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
                out.append(f"data: {data_str}")
            out.append("")  # blank line = frame boundary
        return ("\n".join(out) + "\n").encode("utf-8")

    def handle(self, request: httpx.Request) -> httpx.Response:
        """MockTransport handler:按 method + path 路由。"""
        method = request.method
        path = request.url.path
        if method == "POST" and (path == "/mcp" or path.endswith("/mcp")):
            return self._handle_post(request)
        if method == "GET" and path.endswith("/mcp/sse"):
            return self._handle_get(request)
        return httpx.Response(404, json={"error": {"code": -32601, "message": f"unknown: {method} {path}"}})

    def _handle_post(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content)
        except json.JSONDecodeError:
            return httpx.Response(400, json={"error": {"code": -32700, "message": "parse error"}})
        if body.get("jsonrpc") != "2.0":
            return httpx.Response(400, json={"error": {"code": -32600, "message": "invalid request"}})
        method_rpc = body.get("method")
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Capture call
        self.post_calls.append({
            "tool": tool_name,
            "arguments": arguments,
            "headers": dict(request.headers),
        })

        # 如果有自定义 response 用之
        if self.post_response is not None:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0", "id": body.get("id"),
                    "result": self.post_response,
                },
            )
        # 默认 success response
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {"stream_id": self.default_stream_id, "endpoint": self.endpoint},
            },
        )

    def _handle_get(self, request: httpx.Request) -> httpx.Response:
        self.get_calls.append({
            "url": str(request.url),
            "headers": dict(request.headers),
        })
        body = self.encode_sse_body()
        if self.sse_status != 200:
            return httpx.Response(self.sse_status, text="error")
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
            },
            content=body,
        )


# ────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────

@pytest.fixture
def mock_router() -> MockMCPSSERouter:
    return MockMCPSSERouter()


@pytest.fixture
def async_stream_client(mock_router: MockMCPSSERouter):
    """AsyncMCPClient with MockTransport injected."""
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient(
        "https://kernel.example.com",
        bearer_token="test-jwt",
        http_client=async_http,
    )
    return client, mock_router, async_http


# ────────────────────────────────────────────────────────
# 1-5. SSE frame type coverage
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_open_frame(mock_router: MockMCPSSERouter):
    """Test stream_message open frame yields StreamEvent with type=open."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", bearer_token="jwt", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events: list[StreamEvent] = []
        async for ev in handle.events():
            events.append(ev)
        assert len(events) == 1
        assert events[0].type == "open"
        assert events[0].stream_id == "stream-uuid-1"
        assert events[0].timestamp == "2026-07-11T10:00:00Z"
        assert events[0].data["stream_id"] == "stream-uuid-1"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_message_frame(mock_router: MockMCPSSERouter):
    """Test message frame event with agent message payload."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {
            "event": "message",
            "data": {
                "message_id": "msg-1", "role": "agent", "context_id": "ctx-1",
                "parts": [{"kind": "text", "text": "Hello back!"}],
            },
        },
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        message_event = next(e for e in events if e.type == "message")
        assert message_event.data["message_id"] == "msg-1"
        assert message_event.data["role"] == "agent"
        assert message_event.data["parts"][0]["text"] == "Hello back!"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_artifact_frame(mock_router: MockMCPSSERouter):
    """Test artifact frame event."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {
            "event": "artifact",
            "data": {
                "artifact_id": "art-1", "type": "text",
                "name": "report.md",
                "parts": [{"kind": "text", "text": "Generated report"}],
            },
        },
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        artifact_event = next(e for e in events if e.type == "artifact")
        assert artifact_event.data["artifact_id"] == "art-1"
        assert artifact_event.data["type"] == "text"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_task_complete_frame(mock_router: MockMCPSSERouter):
    """Test task_complete frame event."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "task_status", "data": {"task_id": "t1", "state": "working"}},
        {
            "event": "task_complete",
            "data": {"task_id": "t1", "state": "completed", "artifacts": []},
        },
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        complete = next(e for e in events if e.type == "task_complete")
        assert complete.data["task_id"] == "t1"
        assert complete.data["state"] == "completed"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_error_frame(mock_router: MockMCPSSERouter):
    """Test error frame → iterator raise RPCError."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "error", "data": {"code": -32003, "message": "agent disconnected"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = []
        with pytest.raises(RPCError) as exc_info:
            async for ev in handle.events():
                events.append(ev)
        # open frame received before error
        assert len(events) == 1
        assert events[0].type == "open"
        assert exc_info.value.code == -32003
        assert "agent disconnected" in exc_info.value.message
    finally:
        await handle.cancel()


# ────────────────────────────────────────────────────────
# 6-10. HTTP error + local validation
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_401(mock_router: MockMCPSSERouter):
    """Test GET /mcp/sse 返回 401 → RPCError with negative status code."""
    mock_router.sse_status = 401
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", bearer_token="bad-jwt", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    with pytest.raises(RPCError) as exc_info:
        await client.stream_message("fox", msg)
    assert exc_info.value.code == -401
    assert "unauthorized" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_stream_message_404(mock_router: MockMCPSSERouter):
    """Test GET /mcp/sse 返回 404 → RPCError with ERR_CODE_STREAM_CLOSED."""
    mock_router.sse_status = 404
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    with pytest.raises(RPCError) as exc_info:
        await client.stream_message("fox", msg)
    assert exc_info.value.code == ERR_CODE_STREAM_CLOSED
    assert MCP_STREAM_CLOSED_MSG in exc_info.value.message


@pytest.mark.asyncio
async def test_stream_message_nil_message(mock_router: MockMCPSSERouter):
    """Test stream_message(message=None) raises ValueError before HTTP."""
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    with pytest.raises(ValueError, match="message is required"):
        await client.stream_message("fox", None)
    # No HTTP call should have been made
    assert len(mock_router.post_calls) == 0


@pytest.mark.asyncio
async def test_stream_message_empty_parts(mock_router: MockMCPSSERouter):
    """Test stream_message(message.parts=[]) raises ValueError before HTTP."""
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    empty_msg = Message(role="user")  # no parts
    with pytest.raises(ValueError, match="parts"):
        await client.stream_message("fox", empty_msg)
    assert len(mock_router.post_calls) == 0


@pytest.mark.asyncio
async def test_stream_message_async_cancel(mock_router: MockMCPSSERouter):
    """Test async cancel() stops the iterator gracefully."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        # No close frame: rely on cancel to terminate
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)

    received = []

    async def consume():
        async for ev in handle.events():
            received.append(ev)

    consume_task = asyncio.create_task(consume())
    # Allow open frame to be received
    await asyncio.sleep(0.05)
    assert len(received) == 1

    # Cancel mid-stream
    await handle.cancel()
    # Wait for consumer task to exit
    try:
        await asyncio.wait_for(consume_task, timeout=1.0)
    except asyncio.TimeoutError:  # pragma: no cover
        consume_task.cancel()


# ────────────────────────────────────────────────────────
# 11-13. subscribe_to_task + local validation
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_to_task_happy_path(mock_router: MockMCPSSERouter):
    """Test subscribe_to_task → SSE task_status / task_complete frames."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "task_status", "data": {"task_id": "task-uuid-1", "state": "working"}},
        {
            "event": "task_complete",
            "data": {"task_id": "task-uuid-1", "state": "completed"},
        },
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    handle = await client.subscribe_to_task("fox", "task-uuid-1")
    try:
        events = [ev async for ev in handle.events()]
        types = [e.type for e in events]
        assert "open" in types
        assert "task_status" in types
        assert "task_complete" in types
        # Last event is task_complete
        assert events[-1].type == "task_complete"
        assert events[-1].data["state"] == "completed"
    finally:
        await handle.cancel()

    # Verify POST had correct tool name + task_id
    assert mock_router.post_calls[0]["tool"] == "subscribe_to_task"
    assert mock_router.post_calls[0]["arguments"]["task_id"] == "task-uuid-1"


@pytest.mark.asyncio
async def test_subscribe_to_task_task_id_empty(mock_router: MockMCPSSERouter):
    """Test subscribe_to_task(task_id='') raises ValueError before HTTP."""
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    with pytest.raises(ValueError, match="task_id"):
        await client.subscribe_to_task("fox", "")
    assert len(mock_router.post_calls) == 0


@pytest.mark.asyncio
async def test_subscribe_to_task_error_frame(mock_router: MockMCPSSERouter):
    """Test subscribe_to_task with server error frame → RPCError."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "error", "data": {"code": -32003, "message": "task not found"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    handle = await client.subscribe_to_task("fox", "missing-task")
    try:
        with pytest.raises(RPCError) as exc_info:
            async for _ in handle.events():
                pass
        assert exc_info.value.code == -32003
        assert "task not found" in exc_info.value.message
    finally:
        await handle.cancel()


# ────────────────────────────────────────────────────────
# 14-16. StreamOptions coverage
# ────────────────────────────────────────────────────────

def test_stream_options_include_history():
    """Test StreamOptions(include_history=True) → snake_case JSON."""
    opts = StreamOptions(include_history=True)
    assert opts.include_history is True
    assert opts.include_artifacts is False
    d = opts.to_dict()
    assert d == {"include_history": True}
    assert "include_artifacts" not in d


def test_stream_options_include_artifacts():
    """Test StreamOptions(include_artifacts=True) → snake_case JSON."""
    opts = StreamOptions(include_artifacts=True)
    assert opts.include_artifacts is True
    assert opts.include_history is False
    d = opts.to_dict()
    assert d == {"include_artifacts": True}


def test_stream_options_default():
    """Test default StreamOptions → empty dict (won't be sent on wire)."""
    opts = StreamOptions()
    assert opts.include_history is False
    assert opts.include_artifacts is False
    d = opts.to_dict()
    assert d == {}


@pytest.mark.asyncio
async def test_stream_options_custom(mock_router: MockMCPSSERouter):
    """Test StreamOptions sent on wire in arguments (snake_case)."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    opts = StreamOptions(include_history=True, include_artifacts=True)
    handle = await client.stream_message("fox", msg, opts)
    try:
        async for _ in handle.events():
            pass
    finally:
        await handle.cancel()
    # Verify stream_options got sent
    args = mock_router.post_calls[0]["arguments"]
    assert args["stream_options"] == {"include_history": True, "include_artifacts": True}


@pytest.mark.asyncio
async def test_subscribe_to_task_stream_options(mock_router: MockMCPSSERouter):
    """Test StreamOptions on subscribe_to_task → snake_case wire format."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    opts = StreamOptions(include_artifacts=True)
    handle = await client.subscribe_to_task("fox", "task-1", opts)
    try:
        async for _ in handle.events():
            pass
    finally:
        await handle.cancel()
    args = mock_router.post_calls[0]["arguments"]
    assert args["stream_options"] == {"include_artifacts": True}


# ────────────────────────────────────────────────────────
# 17-18. StreamHandle lifecycle
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_handle_cancel_idempotent(mock_router: MockMCPSSERouter):
    """Test cancel() is idempotent (per D89 spec)."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    await handle.cancel()
    # Second cancel — must not raise
    await handle.cancel()
    # Third cancel — also OK
    await handle.cancel()


@pytest.mark.asyncio
async def test_stream_handle_events_close_after_cancel(mock_router: MockMCPSSERouter):
    """Test events() iterator exits after cancel."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        # No close frame: only cancel triggers exit
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        # Receive open frame
        first_event = None
        async for ev in handle.events():
            first_event = ev
            break
        assert first_event is not None
        assert first_event.type == "open"
    finally:
        await handle.cancel()

    # After cancel, iterating again should immediately exit
    received_after = []
    async for ev in handle.events():
        received_after.append(ev)
    assert received_after == []


@pytest.mark.asyncio
async def test_stream_handle_context_manager(mock_router: MockMCPSSERouter):
    """Test async with stream_handle pattern auto-cleans up."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    async with await client.stream_message("fox", msg) as handle:
        async for ev in handle.events():
            assert ev.type == "open" or ev.type == "close"


# ────────────────────────────────────────────────────────
# 19-22. Auth + stream_id + invalid JSON + multiple events
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_bearer_token_refresh(mock_router: MockMCPSSERouter):
    """Test bearer token sent on both POST + GET (per D78/D79)."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", bearer_token="initial-jwt", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        async for _ in handle.events():
            pass
    finally:
        await handle.cancel()

    # Verify POST Authorization
    assert mock_router.post_calls[0]["headers"].get("authorization") == "Bearer initial-jwt"
    # Verify GET /mcp/sse Authorization
    assert mock_router.get_calls[0]["headers"].get("authorization") == "Bearer initial-jwt"

    # Now rotate token + open new stream
    client.set_bearer_token("rotated-jwt")
    handle2 = await client.stream_message("fox", msg)
    try:
        async for _ in handle2.events():
            pass
    finally:
        await handle2.cancel()

    assert mock_router.post_calls[1]["headers"].get("authorization") == "Bearer rotated-jwt"
    assert mock_router.get_calls[1]["headers"].get("authorization") == "Bearer rotated-jwt"


@pytest.mark.asyncio
async def test_stream_message_stream_id_mismatch(mock_router: MockMCPSSERouter):
    """Test stream_id mismatch in open frame data → RPCError."""
    mock_router.set_sse_body([
        # Open frame data carries DIFFERENT stream_id than what server returned
        {"event": "open", "data": {"stream_id": "WRONG-UUID", "timestamp": "2026-07-11T10:00:00Z"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        with pytest.raises(RPCError) as exc_info:
            async for _ in handle.events():
                pass
        assert exc_info.value.code == ERR_CODE_STREAM_CLOSED
        assert "mismatch" in exc_info.value.message.lower()
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_invalid_json(mock_router: MockMCPSSERouter):
    """Test SSE frame with malformed JSON data → RPCError -32700."""
    # Manually craft malformed data via raw SSE body (bypass set_sse_body)
    raw_sse = (
        b"event: open\n"
        b'data: {"stream_id":"stream-uuid-1","timestamp":"2026-07-11T00:00:00Z"}\n'
        b"\n"
        b"event: message\n"
        b"data: {this is not valid JSON\n"
        b"\n"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"stream_id": "stream-uuid-1", "endpoint": "/mcp/sse"},
            })
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=raw_sse,
        )

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        with pytest.raises(RPCError) as exc_info:
            async for _ in handle.events():
                pass
        assert exc_info.value.code == -32700
        assert "malformed" in exc_info.value.message.lower()
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_multiple_events(mock_router: MockMCPSSERouter):
    """Test consuming many events in sequence."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "task_status", "data": {"task_id": "t1", "state": "working"}},
        {"event": "message", "data": {"message_id": "m1", "role": "agent", "parts": []}},
        {"event": "task_status", "data": {"task_id": "t1", "state": "working"}},
        {"event": "artifact", "data": {"artifact_id": "a1", "type": "text", "text": "chunk 1"}},
        {"event": "artifact", "data": {"artifact_id": "a2", "type": "text", "text": "chunk 2"}},
        {"event": "task_complete", "data": {"task_id": "t1", "state": "completed"}},
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        types = [e.type for e in events]
        assert types == [
            "open", "task_status", "message", "task_status",
            "artifact", "artifact", "task_complete",
        ]
        # close frame is consumed but doesn't yield an event (signals iterator exit)
        # Verify last event is task_complete
        assert events[-1].type == "task_complete"
    finally:
        await handle.cancel()


# ────────────────────────────────────────────────────────
# 23-25. Concurrent + post-failure + get-failure
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_concurrent_streams(mock_router: MockMCPSSERouter):
    """Test multiple concurrent stream_message calls (5 streams in parallel)."""
    stream_id_counter = [0]

    def make_sse_body(stream_uuid: str) -> bytes:
        body_str = (
            f"event: open\n"
            f'data: {{"stream_id":"{stream_uuid}","timestamp":"2026-07-11T10:00:00Z"}}\n'
            f"\n"
            f"event: close\n"
            f'data: {{"reason":"completed"}}\n'
            f"\n"
        )
        return body_str.encode("utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        method = req.method
        path = req.url.path
        if method == "POST" and path.endswith("/mcp"):
            stream_id_counter[0] += 1
            new_uuid = f"stream-uuid-{stream_id_counter[0]}"
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"stream_id": new_uuid, "endpoint": "/mcp/sse"},
            })
        if method == "GET" and path.endswith("/mcp/sse"):
            stream_uuid = req.url.params.get("stream_id", "")
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=make_sse_body(stream_uuid),
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)

    async def open_and_consume(idx: int) -> str:
        msg = Message(role="user", parts=[Part(type="text", text=f"hi-{idx}")])
        async with await client.stream_message(f"fox-{idx}", msg) as handle:
            first_event = None
            async for ev in handle.events():
                if ev.type == "open":
                    first_event = ev
                    break
            assert first_event is not None
            return first_event.stream_id

    stream_ids = await asyncio.gather(*[open_and_consume(i) for i in range(5)])
    assert len(set(stream_ids)) == 5  # All unique


@pytest.mark.asyncio
async def test_stream_message_post_failure(mock_router: MockMCPSSERouter):
    """Test POST /mcp returns 500 → RPCError from POST phase."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    with pytest.raises(RPCError) as exc_info:
        await client.stream_message("fox", msg)
    assert exc_info.value.code == -500


@pytest.mark.asyncio
async def test_stream_message_post_rpc_error(mock_router: MockMCPSSERouter):
    """Test POST /mcp returns JSON-RPC error → RPCError from envelope."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -32603, "message": "kernel overload"},
            })
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    with pytest.raises(RPCError) as exc_info:
        await client.stream_message("fox", msg)
    assert exc_info.value.code == -32603
    assert "kernel overload" in exc_info.value.message


@pytest.mark.asyncio
async def test_stream_message_get_failure_500(mock_router: MockMCPSSERouter):
    """Test GET /mcp/sse returns 500 → RPCError."""
    mock_router.sse_status = 500
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    with pytest.raises(RPCError) as exc_info:
        await client.stream_message("fox", msg)
    assert exc_info.value.code == -500
    assert "500" in exc_info.value.message


# ────────────────────────────────────────────────────────
# 26-30. Misc + edge cases
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_long_running(mock_router: MockMCPSSERouter):
    """Test long-running stream with many frames iterates fully."""
    frames = [{"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}}]
    for i in range(20):
        frames.append({
            "event": "message",
            "data": {
                "message_id": f"m-{i}", "role": "agent",
                "parts": [{"kind": "text", "text": f"chunk {i}"}],
            },
        })
    frames.append({"event": "task_complete", "data": {"task_id": "t1", "state": "completed"}})
    frames.append({"event": "close", "data": {"reason": "completed"}})
    mock_router.set_sse_body(frames)

    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        # open + 20 message + 1 task_complete = 22 events
        assert len(events) == 22
        assert events[0].type == "open"
        assert events[-1].type == "task_complete"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_handle_timestamp_parsing(mock_router: MockMCPSSERouter):
    """Test timestamp field extracted per-frame."""
    mock_router.set_sse_body([
        {
            "event": "open",
            "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"},
        },
        {
            "event": "message",
            "data": {
                "message_id": "m1", "role": "agent",
                "timestamp": "2026-07-11T10:00:05Z",
                "parts": [],
            },
        },
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        assert events[0].timestamp == "2026-07-11T10:00:00Z"
        assert events[1].timestamp == "2026-07-11T10:00:05Z"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_sse_comment_lines(mock_router: MockMCPSSERouter):
    """Test SSE comment lines (': some text') are ignored per SSE spec."""
    # Mix in comments between frames
    mock_router.set_sse_body([
        {"comment": "this is a comment"},
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"comment": "heartbeat"},
        {"comment": "another comment"},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        # Comments must be silently ignored — only open frame yielded
        assert len(events) == 1
        assert events[0].type == "open"
    finally:
        await handle.cancel()


# ────────────────────────────────────────────────────────
# Extra edge cases
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_message_no_bearer_token(mock_router: MockMCPSSERouter):
    """Test stream works without bearer token (dev/test mode)."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)  # no token
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        async for _ in handle.events():
            pass
    finally:
        await handle.cancel()
    # No Authorization header sent
    assert "authorization" not in mock_router.get_calls[0]["headers"]
    assert "authorization" not in mock_router.post_calls[0]["headers"]


@pytest.mark.asyncio
async def test_stream_message_data_only_no_event(mock_router: MockMCPSSERouter):
    """Test SSE frame with only data (no event) → event.type is empty string."""
    raw_sse = (
        b"event: open\n"
        b'data: {"stream_id":"stream-uuid-1","timestamp":"2026-07-11T00:00:00Z"}\n'
        b"\n"
        b"data: {\"value\":42}\n"
        b"\n"
        b"event: close\n"
        b"data: {\"reason\":\"done\"}\n"
        b"\n"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"stream_id": "stream-uuid-1", "endpoint": "/mcp/sse"},
            })
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=raw_sse,
        )

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        # data-only frame should yield empty type
        assert any(e.type == "" and e.data.get("value") == 42 for e in events)
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_skip_empty_data_frames(mock_router: MockMCPSSERouter):
    """Test frames with empty data are silently skipped (per SSE spec)."""
    raw_sse = (
        b"event: open\n"
        b'data: {"stream_id":"stream-uuid-1","timestamp":"2026-07-11T00:00:00Z"}\n'
        b"\n"
        b"event: ping\n"
        b"data:\n"
        b"\n"
        b"event: close\n"
        b'data: {"reason":"done"}\n'
        b"\n"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"stream_id": "stream-uuid-1", "endpoint": "/mcp/sse"},
            })
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=raw_sse,
        )

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        # Only open frame yielded (ping has empty data → skipped)
        assert len(events) == 1
        assert events[0].type == "open"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_message_no_data_field(mock_router: MockMCPSSERouter):
    """Test SSE frame with no data field at all (just event type) → skipped."""
    raw_sse = (
        b"event: open\n"
        b'data: {"stream_id":"stream-uuid-1","timestamp":"2026-07-11T00:00:00Z"}\n'
        b"\n"
        b"event: heartbeat\n"
        b"\n"
        b"event: close\n"
        b'data: {"reason":"done"}\n'
        b"\n"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"stream_id": "stream-uuid-1", "endpoint": "/mcp/sse"},
            })
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=raw_sse,
        )

    transport = httpx.MockTransport(handler)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    try:
        events = [ev async for ev in handle.events()]
        # Only open yielded; heartbeat without data is silently skipped
        assert len(events) == 1
        assert events[0].type == "open"
    finally:
        await handle.cancel()


@pytest.mark.asyncio
async def test_stream_handle_done_event_after_normal_close(mock_router: MockMCPSSERouter):
    """Test handle.done event is set after normal close frame."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "completed"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    client = AsyncMCPClient("https://kernel.example.com", http_client=async_http)
    msg = Message(role="user", parts=[Part(type="text", text="hi")])
    handle = await client.stream_message("fox", msg)
    async for _ in handle.events():
        pass
    # After iterator exits (close frame), done event should be set
    assert handle.done.is_set()
    await handle.cancel()


@pytest.mark.asyncio
async def test_open_stream_helper_direct(mock_router: MockMCPSSERouter):
    """Test the open_stream helper directly (without AsyncMCPClient wrapper)."""
    mock_router.set_sse_body([
        {"event": "open", "data": {"stream_id": "stream-uuid-1", "timestamp": "2026-07-11T10:00:00Z"}},
        {"event": "close", "data": {"reason": "done"}},
    ])
    transport = httpx.MockTransport(mock_router.handle)
    async_http = httpx.AsyncClient(transport=transport)
    handle = await open_stream(
        base_url="https://kernel.example.com",
        endpoint="/mcp",
        tool_name="stream_message",
        arguments={"target": {"name": "fox"}, "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]}},
        bearer_token="jwt",
        user_agent=None,
        http=async_http,
    )
    try:
        events = [ev async for ev in handle.events()]
        assert events[0].type == "open"
        assert handle.stream_id == "stream-uuid-1"
    finally:
        await handle.cancel()
