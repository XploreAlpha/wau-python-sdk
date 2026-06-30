"""ChatService — wau-edge OpenAI 兼容层封装(per v0.9.0 M3 §3.7, D20 architecture-pivot)

替换 v0.8.0 时代的 Tasks().Submit 路径(走 /registry/tasks/submit 老路径):
  旧: c.tasks.submit(SubmitRequest(prompt=...))   → wau-core :18400 /registry/tasks/submit
  新: c.chat.completions(ChatCompletionRequest(...)) → wau-edge :18402 /v1/chat/completions

沿用 handshake.py 同步+异步双版本模式 + HandshakeError 错误码处理。

完整链路(per M3 §4.5.1):
  bot → wau-edge :18402 /v1/chat/completions
       → wau-llm-router :18403 /v1/resolve(决定 userToken + model)
       → new-api :3000 /v1/chat/completions → LLM provider
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wau_sdk.types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

if TYPE_CHECKING:
    pass


class ChatService:
    """同步 ChatService — wau-edge OpenAI 兼容层主入口

    用法::

        with wau_sdk.Client("http://localhost:18402") as c:  # wau-edge 端口
            resp = c.chat.completions(ChatCompletionRequest(
                model="gpt-4o-mini",
                messages=[ChatMessage(role="user", content="hello")],
            ))
            print(resp.choices[0].message.content)
    """

    def __init__(self, client) -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport = client._transport
        self._options = client.options

    def completions(self, req: ChatCompletionRequest) -> ChatCompletionResponse:
        """POST /v1/chat/completions

        :raises ValueError: Model / Messages 客户端校验失败
        :raises APIError: HTTP 4xx/5xx(wau-edge 错误码透传)
        """
        if not req.model:
            raise ValueError("ChatCompletionRequest.model is required")
        if not req.messages:
            raise ValueError("ChatCompletionRequest.messages must not be empty")
        # 序列化: dataclass → dict
        body: dict = {
            "model": req.model,
            "messages": [
                {k: v for k, v in {
                    "role": m.role,
                    "content": m.content,
                    "name": m.name,
                }.items() if v}
                for m in req.messages
            ],
        }
        if req.stream:
            body["stream"] = True
        if req.universe:
            body["universe"] = req.universe
        if req.metadata:
            body["metadata"] = req.metadata
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens > 0:
            body["max_tokens"] = req.max_tokens

        data = self._transport.request("POST", "/v1/chat/completions", body=body)
        # 解析响应: dict → dataclass
        choices = [
            {
                "index": c.get("index", 0),
                "message": {
                    "role": c.get("message", {}).get("role", ""),
                    "content": c.get("message", {}).get("content", ""),
                    "name": c.get("message", {}).get("name", ""),
                },
                "finish_reason": c.get("finish_reason", ""),
            }
            for c in data.get("choices", [])
        ]
        usage_data = data.get("usage", {})
        return ChatCompletionResponse(
            id=data.get("id", ""),
            object=data.get("object", "chat.completion"),
            created=data.get("created", 0),
            model=data.get("model", ""),
            choices=choices,
            usage={
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            },
            reason=data.get("reason", ""),
        )


class AsyncChatService:
    """异步 ChatService(API 镜像同步版,per handshake.py 模式)"""

    def __init__(self, client) -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport = client._transport
        self._options = client.options

    async def completions(self, req: ChatCompletionRequest) -> ChatCompletionResponse:
        if not req.model:
            raise ValueError("ChatCompletionRequest.model is required")
        if not req.messages:
            raise ValueError("ChatCompletionRequest.messages must not be empty")
        body: dict = {
            "model": req.model,
            "messages": [
                {k: v for k, v in {
                    "role": m.role,
                    "content": m.content,
                    "name": m.name,
                }.items() if v}
                for m in req.messages
            ],
        }
        if req.stream:
            body["stream"] = True
        if req.universe:
            body["universe"] = req.universe
        if req.metadata:
            body["metadata"] = req.metadata
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens > 0:
            body["max_tokens"] = req.max_tokens

        data = await self._transport.request("POST", "/v1/chat/completions", body=body)
        choices = [
            {
                "index": c.get("index", 0),
                "message": {
                    "role": c.get("message", {}).get("role", ""),
                    "content": c.get("message", {}).get("content", ""),
                    "name": c.get("message", {}).get("name", ""),
                },
                "finish_reason": c.get("finish_reason", ""),
            }
            for c in data.get("choices", [])
        ]
        usage_data = data.get("usage", {})
        return ChatCompletionResponse(
            id=data.get("id", ""),
            object=data.get("object", "chat.completion"),
            created=data.get("created", 0),
            model=data.get("model", ""),
            choices=choices,
            usage={
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            },
            reason=data.get("reason", ""),
        )
