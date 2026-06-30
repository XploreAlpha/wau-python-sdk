"""v0.9.0 M3 §3.7 — ChatService 单测(respx mock wau-edge OpenAI 兼容层)

5 case(per plan §B.7):
  1. happy path(POST → OpenAI 响应解析)
  2. empty model → ValueError 客户端校验
  3. empty messages → ValueError 客户端校验
  4. server 4xx(InvalidRequest -32600) → APIError
  5. 异步 happy path(async client)
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


# ============== Case 5:async happy path ==============

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
