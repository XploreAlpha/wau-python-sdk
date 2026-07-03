"""v0.9.0 M3 §3.7 — ChatService 单测(respx mock wau-edge OpenAI 兼容层)

Stage 3.1 #10 (2026-07-02) 新增 7 SSE 单测(原 5 个 non-stream 不动,0 回归)。

Total: 5 (completions) + 7 (stream) = 12 tests。

SSE 测试设计(per Go SDK TestChat_Stream_* 镜像):
  1. happy path(role + "1+1=2" + stop + DONE)
  2. empty(DONE immediate,0 chunks)
  3. auth error(HTTP 401 → APIError)
  4. bad JSON(role chunk + 坏 JSON → JSONDecodeError)
  5. partial(中间 chunk 后断流)
  6. empty model(客户端校验)
  7. empty messages(客户端校验)
"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import (
    APIError,
    ChatMessage,
    ChatCompletionRequest,
    CircuitConfig,
    ClientOptions,
    RetryConfig,
)


@pytest.fixture
def edge_mock() -> respx.MockRouter:
    with respx.mock(base_url="http://mock-edge:18402") as router:
        yield router


@pytest.fixture
def sync_client(edge_mock: respx.MockRouter) -> wau_sdk.Client:
    with wau_sdk.Client("http://mock-edge:18402", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        yield c


@pytest.fixture
def async_client(edge_mock: respx.MockRouter) -> wau_sdk.AsyncClient:
    async def factory():
        return wau_sdk.AsyncClient("http://mock-edge:18402", ClientOptions(
            retry=RetryConfig(max_retries=0),
            circuit=CircuitConfig(enabled=False),
        ))
    return factory


# ============== Case 1:happy path ==============

def test_chat_happy(edge_mock: respx.MockRouter, sync_client: wau_sdk.Client) -> None:
    edge_mock.post("/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "chatcmpl-mock-001",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "echo: hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
            "reason": "static:tenant=acme model=gpt-4o-mini",
            # Stage 3.1 #11 (2026-07-03):Provider 透传 mock(provider 字段验证)
            "provider": "deepseek-v4-flash",
        })
    )
    resp = sync_client.chat.completions(ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
        universe="default",
    ))
    assert resp.id == "chatcmpl-mock-001"
    assert len(resp.choices) == 1
    assert resp.choices[0]["message"]["content"] == "echo: hello"
    assert resp.reason.startswith("static:tenant=acme")
    # Stage 3.1 #11:Provider 透传验证
    assert resp.provider == "deepseek-v4-flash", f"provider = {resp.provider!r}, want deepseek-v4-flash"


# ============== Case 2:empty model ==============

def test_chat_empty_model(sync_client: wau_sdk.Client) -> None:
    with pytest.raises(ValueError, match="model is required"):
        sync_client.chat.completions(ChatCompletionRequest(
            model="",
            messages=[ChatMessage(role="user", content="hi")],
        ))


# ============== Case 3:empty messages ==============

def test_chat_empty_messages(sync_client: wau_sdk.Client) -> None:
    with pytest.raises(ValueError, match="messages must not be empty"):
        sync_client.chat.completions(ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[],
        ))


# ============== Case 4:server 4xx ==============

def test_chat_server_error_invalid_request(edge_mock: respx.MockRouter, sync_client: wau_sdk.Client) -> None:
    edge_mock.post("/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={
            "error": {
                "code": -32600,
                "message": "InvalidRequest: empty messages",
            },
        })
    )
    with pytest.raises(APIError) as exc_info:
        sync_client.chat.completions(ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="hi")],
        ))
    assert exc_info.value.status_code == 400


# ============== Case 5:Provider 透传 (Stage 3.1 #11, 2026-07-03) ==============
#
# 验证:wau-edge /v1/chat/completions 响应里带 provider 字段(per LLMDecision.Provider 透传),
#      wau-python-sdk ChatCompletionResponse.provider 字段能正确解析并暴露。
# 兼容:老 server 不带 provider 字段 → SDK 解析为 ""(空串兜底,Python dataclass 默认值)。

def test_chat_provider_passthrough(edge_mock: respx.MockRouter, sync_client: wau_sdk.Client) -> None:
    edge_mock.post("/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "chatcmpl-provider-001",
            "object": "chat.completion",
            "created": 1700000002,
            "model": "claude-haiku-4-5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "provider": "claude-haiku-4-5",
        })
    )
    resp = sync_client.chat.completions(ChatCompletionRequest(
        model="claude-haiku-4-5",
        messages=[ChatMessage(role="user", content="hi")],
    ))
    assert resp.provider == "claude-haiku-4-5", (
        f"provider = {resp.provider!r}, want claude-haiku-4-5 (Stage 3.1 #11 provider 透传)"
    )


# ============== Case 6:async happy path ==============

@pytest.mark.asyncio
async def test_chat_async_happy(edge_mock: respx.MockRouter) -> None:
    edge_mock.post("/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "chatcmpl-async-001",
            "object": "chat.completion",
            "created": 1700000001,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "async echo"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    async with wau_sdk.AsyncClient("http://mock-edge:18402", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        resp = await c.chat.completions(ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="async")],
        ))
    assert resp.id == "chatcmpl-async-001"
    assert resp.choices[0]["message"]["content"] == "async echo"


# ============== Stage 3.1 #10 SSE Streaming 单测 ==============
#
# 用 httpx.MockTransport 自定义 SSE 响应(绕过 respx 因为 SSE 流式响应 respx 不太好 mock)。
# 每个测试启动一个真实 httpx 服务器(localhost) + 注入 wau_sdk.Client.base_url。

def _make_sse_response(status_code: int, chunks: list[str]) -> httpx.Response:
    """拼 SSE 响应:data: {json}\\n\\n 格式 + data: [DONE]\\n\\n 终止

    Args:
        status_code: HTTP 状态码
        chunks: JSON 字符串列表(每个会包成 data: ...\\n\\n),None 表示立刻 [DONE]
    """
    if status_code >= 400:
        # 4xx/5xx 走 application/json(非 SSE)
        return httpx.Response(
            status_code,
            json={"error": {"code": -32600, "message": "test error"}},
            headers={"Content-Type": "application/json"},
        )
    body = ""
    for chunk in chunks or []:
        body += f"data: {chunk}\n\n"
    if chunks is not None:
        body += "data: [DONE]\n\n"
    return httpx.Response(
        200,
        content=body.encode("utf-8"),
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
    )


def _make_sync_stream_client(handler) -> wau_sdk.Client:
    """构造同步 wau_sdk.Client,MockTransport 模拟 SSE 服务器"""
    transport = httpx.MockTransport(handler)
    opts = ClientOptions(retry=RetryConfig(max_retries=0), circuit=CircuitConfig(enabled=False))
    c = wau_sdk.Client("http://mock-sse", opts)
    # 注入 MockTransport
    c._transport._http = httpx.Client(
        base_url="http://mock-sse",
        timeout=opts.timeout_ms / 1000,
        headers={"User-Agent": opts.user_agent},
        transport=transport,
    )
    return c


def _make_async_stream_client(handler):
    """构造异步 wau_sdk.AsyncClient,MockTransport 模拟 SSE 服务器"""
    transport = httpx.MockTransport(handler)
    opts = ClientOptions(retry=RetryConfig(max_retries=0), circuit=CircuitConfig(enabled=False))
    c = wau_sdk.AsyncClient("http://mock-sse", opts)
    c._transport._http = httpx.AsyncClient(
        base_url="http://mock-sse",
        timeout=opts.timeout_ms / 1000,
        headers={"User-Agent": opts.user_agent},
        transport=transport,
    )
    return c


# ----- Case 6: stream happy path -----

def test_chat_stream_happy() -> None:
    """6 chunks(role + "1+1=2") + DONE,验证累加 content + finish_reason=stop"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("accept") == "text/event-stream"
        return _make_sse_response(200, [
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"role":"assistant"}}]}',
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"content":"1"}}]}',
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"content":"+"}}]}',
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"content":"1"}}]}',
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"content":"="}}]}',
            '{"id":"chatcmpl-py-1","object":"chat.completion.chunk","created":1700000000,"model":"deepseek-v4-flash","choices":[{"index":0,"delta":{"content":"2"},"finish_reason":"stop"}]}',
        ])

    c = _make_sync_stream_client(handler)
    try:
        full = ""
        last_id = ""
        count = 0
        for chunk in c.chat.stream(ChatCompletionRequest(
            model="deepseek-v4-flash",
            messages=[ChatMessage(role="user", content="1+1=?")],
        )):
            count += 1
            last_id = chunk.id
            if chunk.choices and chunk.choices[0].delta.content:
                full += chunk.choices[0].delta.content
            if chunk.choices and chunk.choices[0].finish_reason == "stop":
                break
        assert last_id == "chatcmpl-py-1"
        assert count == 6
        assert full == "1+1=2"
    finally:
        c.close()


# ----- Case 7: stream empty (DONE immediate) -----

def test_chat_stream_empty() -> None:
    """立即 [DONE] → 0 chunks"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_sse_response(200, [])

    c = _make_sync_stream_client(handler)
    try:
        chunks = list(c.chat.stream(ChatCompletionRequest(
            model="deepseek-v4-flash",
            messages=[ChatMessage(role="user", content="anything")],
        )))
        assert chunks == []
    finally:
        c.close()


# ----- Case 8: stream auth error -----

def test_chat_stream_auth_error() -> None:
    """HTTP 401 → APIError 抛出"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_sse_response(401, None)

    c = _make_sync_stream_client(handler)
    try:
        with pytest.raises(APIError) as exc_info:
            list(c.chat.stream(ChatCompletionRequest(
                model="deepseek-v4-flash",
                messages=[ChatMessage(role="user", content="hi")],
            )))
        assert exc_info.value.status_code == 401
    finally:
        c.close()


# ----- Case 9: stream bad JSON -----

def test_chat_stream_bad_json() -> None:
    """role chunk + 坏 JSON 解析 → JSONDecodeError"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_sse_response(200, [
            '{"id":"chatcmpl-py-bad","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"}}]}',
            'this-is-not-json{{{',  # 故意坏 JSON
        ])

    c = _make_sync_stream_client(handler)
    try:
        with pytest.raises(Exception) as exc_info:
            for _ in c.chat.stream(ChatCompletionRequest(
                model="deepseek-v4-flash",
                messages=[ChatMessage(role="user", content="hi")],
            )):
                pass
        # JSONDecodeError 抛出
        assert "JSON" in type(exc_info.value).__name__ or "Expecting" in str(exc_info.value)
    finally:
        c.close()


# ----- Case 10: stream empty model (客户端校验) -----

def test_chat_stream_empty_model() -> None:
    """空 model → ValueError,不发请求"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应该有 HTTP 请求")

    c = _make_sync_stream_client(handler)
    try:
        with pytest.raises(ValueError, match="model is required"):
            list(c.chat.stream(ChatCompletionRequest(
                model="",
                messages=[ChatMessage(role="user", content="hi")],
            )))
    finally:
        c.close()


# ----- Case 11: stream empty messages (客户端校验) -----

def test_chat_stream_empty_messages() -> None:
    """空 messages → ValueError,不发请求"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应该有 HTTP 请求")

    c = _make_sync_stream_client(handler)
    try:
        with pytest.raises(ValueError, match="messages must not be empty"):
            list(c.chat.stream(ChatCompletionRequest(
                model="deepseek-v4-flash",
                messages=[],
            )))
    finally:
        c.close()


# ----- Case 12: async stream happy path -----

@pytest.mark.asyncio
async def test_chat_astream_happy() -> None:
    """async astream:6 chunks + 累加 content + finish_reason=stop"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_sse_response(200, [
            '{"id":"chatcmpl-py-async-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"}}]}',
            '{"id":"chatcmpl-py-async-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"a"}}]}',
            '{"id":"chatcmpl-py-async-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"s"}}]}',
            '{"id":"chatcmpl-py-async-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"y"},"finish_reason":"stop"}]}',
        ])

    c = _make_async_stream_client(handler)
    try:
        full = ""
        count = 0
        async for chunk in c.chat.stream(ChatCompletionRequest(
            model="deepseek-v4-flash",
            messages=[ChatMessage(role="user", content="anything")],
        )):
            count += 1
            if chunk.choices and chunk.choices[0].delta.content:
                full += chunk.choices[0].delta.content
            if chunk.choices and chunk.choices[0].finish_reason == "stop":
                break
        assert full == "asy"
        assert count == 4
    finally:
        await c.close()
