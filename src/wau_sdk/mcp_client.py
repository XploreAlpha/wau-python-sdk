"""MCP client (wau-python-sdk v1.3.2, per D87.6).

⭐ v1.0.0 D87.6 W3 + W4-W5 实装(2026-07-11)。

5 SDK 共享 wire format:JSON-RPC 2.0 over HTTP at POST {base_url}/mcp
(跟 WAU-core-kernel internal/protocol/mcp/server.go handleMCP 对齐)。

本模块 = 8 sync tool wrapper (HealthCheck / ParseAgentCard / SendMessage /
GetTask / ListTasks / CancelTask / CreateTaskPushNotificationConfig /
GetExtendedAgentCard) + JSON-RPC envelope + sync/async 双版本。
2 SSE streaming tool (stream_message / subscribe_to_task) deferred to W5+。

用法::

    sync:
        mcp = MCPClient("https://kernel.example.com", bearer_token="oauth-jwt")
        card = mcp.parse_agent_card(b'{"name":"Fox"}')

    async:
        async with AsyncMCPClient("https://kernel.example.com", bearer_token=...) as mcp:
            card = await mcp.parse_agent_card(b'{"name":"Fox"}')

协议合规:
  - D60 additive: 0 改老 SDK,新增独立子模块(跟 chat.py / bot/ / ucp_* 平级)
  - D13 byte-equal: JSON wire format 5 SDK 一致(per design doc §二)
  - D78/D79/D80: MCP OAuth 2.0 identity_linking bearer token(跟 UCP client 走同一通道)
  - D87 ⭐⭐: 本模块 = D87.6 Python SDK MCP client 实装(W3-launch-SOP §3.3 拍板)

设计原则:
  - httpx.Client/AsyncClient 由 caller 注入(测试用 MockTransport,生产用真 httpx)
  - 不引入 Pydantic,用 @dataclass(跟 wau_sdk.ucp_dto.py 一致)
  - 错误统一抛 RPCError(JSON-RPC 2.0 envelope),跟 wau-go-sdk mcpclient.RPCError 字段对齐
  - Bearer token 走 OAuth 2.0 identity_linking(W3 stub;W5+ 加 refresh flow)
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

import httpx

from wau_sdk.mcp_auth import build_headers, set_bearer_token
from wau_sdk.mcp_dto import (
    AgentCard,
    Artifact,
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
from wau_sdk.mcp_errors import RPCError
from wau_sdk.mcp_tools import (
    ALL_TOOL_NAMES,
    TOOL_CANCEL_TASK,
    TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG,
    TOOL_GET_EXTENDED_AGENT_CARD,
    TOOL_GET_TASK,
    TOOL_HEALTH_CHECK,
    TOOL_LIST_TASKS,
    TOOL_PARSE_AGENT_CARD,
    TOOL_SEND_MESSAGE,
    is_streaming_tool,
)


# ────────────────────────────────────────────────────────
# ID generator(per JSON-RPC 2.0 spec,id 可为 string|number|null)
# ────────────────────────────────────────────────────────

_id_counter = itertools.count(1)


def _generate_id() -> int:
    return next(_id_counter)


def _to_dict(obj: Any) -> Any:
    """递归转 dataclass / list / dict 到 plain dict (JSON-serializable)。"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    return obj


def _build_tool_params(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """构造 tools/call params:{name, arguments} envelope(per JSON-RPC 2.0 + MCP spec)。"""
    return {"name": tool_name, "arguments": arguments}


def _normalize_target(target: Any) -> Any:
    """target 接受 string(agent name) 或 dict(AgentRef),统一为 dict。

    跟 kernel handler.routeToProtocol 接受两种类型对齐。
    """
    if target is None:
        raise ValueError("mcpclient: target is required")
    if isinstance(target, str):
        return {"name": target}
    if isinstance(target, dict):
        return target
    raise TypeError(f"mcpclient: target must be str or dict, got {type(target).__name__}")


def _build_parse_agent_card_params(raw: Any) -> dict[str, Any]:
    """构造 parse_agent_card 的 arguments(支持 str / bytes / dict 3 种 input)。"""
    if raw is None:
        raise ValueError("mcpclient: raw is required")
    if isinstance(raw, (bytes, bytearray)):
        import base64
        # bytes 直接传(base64 让 kernel 端可还原)
        return _build_tool_params(
            TOOL_PARSE_AGENT_CARD, {"raw": base64.b64encode(bytes(raw)).decode("ascii")}
        )
    if isinstance(raw, str):
        return _build_tool_params(TOOL_PARSE_AGENT_CARD, {"raw": raw})
    if isinstance(raw, dict):
        return _build_tool_params(TOOL_PARSE_AGENT_CARD, {"raw": _to_dict(raw)})
    raise TypeError(
        f"mcpclient: raw must be str|bytes|dict, got {type(raw).__name__}"
    )


# ────────────────────────────────────────────────────────
# MCPClient — sync 版本
# ────────────────────────────────────────────────────────

class MCPClient:
    """MCP client(发 JSON-RPC 2.0 请求到 kernel /mcp 端点)。

    用法::

        cli = MCPClient("https://kernel.example.com",
                        bearer_token="oauth-jwt",
                        http_client=httpx.Client(timeout=30.0))
        card = cli.parse_agent_card(b'{"name":"Fox"}')
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        endpoint: str = "/mcp",
        user_agent: Optional[str] = None,
    ) -> None:
        if not base_url:
            raise ValueError("mcpclient: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint
        self._bearer_token = bearer_token
        self._user_agent = user_agent
        # caller 不传 → 自建一个(默认);传了就复用(测试用 MockTransport)
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client()

    def close(self) -> None:
        """关闭 MCPClient(释放 owned http client)。"""
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ── auth helpers ─────────────────────────────────────
    def set_bearer_token(self, token: str) -> None:
        """运行时更新 bearer token(W5+ refresh flow 用)。"""
        self._bearer_token = token

    # ── 8 sync tool wrappers ─────────────────────────────
    def health_check(self, target: Any) -> HealthCheckResult:
        """调 health_check tool(per design doc §二.2.3 tool 1)。"""
        params = _build_tool_params(TOOL_HEALTH_CHECK, {"target": _normalize_target(target)})
        out = self._call_tool(params, HealthCheckResult)
        return out

    def parse_agent_card(self, raw: Any) -> AgentCard:
        """调 parse_agent_card tool(per design doc §二.2.3 tool 2)。"""
        params = _build_parse_agent_card_params(raw)
        return self._call_tool(params, AgentCard)

    def send_message(self, target: Any, message: Message) -> Task:
        """调 send_message tool(per design doc §二.2.3 tool 3,最常用)。

        message 必填 Role + 至少 1 个 Part(per kernel handleSendMessage 校验)。
        """
        if message is None:
            raise ValueError("mcpclient: message is required")
        if not message.parts:
            raise ValueError("mcpclient: message.parts must have at least 1 item")
        params = _build_tool_params(
            TOOL_SEND_MESSAGE,
            {"target": _normalize_target(target), "message": _to_dict(message)},
        )
        return self._call_tool(params, Task)

    def get_task(self, target: Any, task_id: str) -> Task:
        """调 get_task tool(per design doc §二.2.3 tool 5)。"""
        if not task_id:
            raise ValueError("mcpclient: task_id is required")
        params = _build_tool_params(
            TOOL_GET_TASK, {"target": _normalize_target(target), "task_id": task_id}
        )
        return self._call_tool(params, Task)

    def list_tasks(self, target: Any, filter: Optional[ListTasksFilter] = None) -> ListTasksResult:
        """调 list_tasks tool(per design doc §二.2.3 tool 6)。"""
        args: dict[str, Any] = {"target": _normalize_target(target)}
        if filter is not None:
            args["filter"] = _to_dict(filter)
        params = _build_tool_params(TOOL_LIST_TASKS, args)
        return self._call_tool(params, ListTasksResult)

    def cancel_task(self, target: Any, task_id: str) -> Task:
        """调 cancel_task tool(per design doc §二.2.3 tool 7)。"""
        if not task_id:
            raise ValueError("mcpclient: task_id is required")
        params = _build_tool_params(
            TOOL_CANCEL_TASK, {"target": _normalize_target(target), "task_id": task_id}
        )
        return self._call_tool(params, Task)

    def create_task_push_notification_config(
        self, target: Any, config: PushConfig
    ) -> PushConfigResult:
        """调 create_task_push_notification_config tool(per design doc §二.2.3 tool 9)。"""
        if config is None or not config.url:
            raise ValueError("mcpclient: config.url is required")
        params = _build_tool_params(
            TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG,
            {"target": _normalize_target(target), "config": _to_dict(config)},
        )
        return self._call_tool(params, PushConfigResult)

    def get_extended_agent_card(self, target: Any) -> ExtendedAgentCard:
        """调 get_extended_agent_card tool(per design doc §二.2.3 tool 10)。"""
        params = _build_tool_params(
            TOOL_GET_EXTENDED_AGENT_CARD, {"target": _normalize_target(target)}
        )
        return self._call_tool(params, ExtendedAgentCard)

    # ── JSON-RPC 2.0 dispatcher ──────────────────────────
    def _call_tool(self, params: dict[str, Any], out_class: type) -> Any:
        """通用 JSON-RPC 2.0 tools/call dispatch + 反序列化到 out_class。"""
        envelope = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": params,
            "id": _generate_id(),
        }
        headers = build_headers(bearer_token=self._bearer_token, user_agent=self._user_agent)
        resp = self._http.post(self._base_url + self._endpoint, json=envelope, headers=headers)
        return self._handle_response(resp, out_class)

    @staticmethod
    def _handle_response(resp: httpx.Response, out_class: type) -> Any:
        """解析 kernel JSON-RPC 2.0 envelope(成功 / 错误 envelope / HTTP 错误)。"""
        # 4xx/5xx → 期望仍是 JSON-RPC envelope,但 fallback HTTP error
        if resp.status_code >= 400:
            try:
                payload = resp.json()
                if isinstance(payload, dict) and "error" in payload:
                    raise RPCError.from_dict(payload["error"])
            except (ValueError, RPCError) as e:
                if isinstance(e, RPCError):
                    raise
            raise RPCError(
                code=resp.status_code * -1,  # 转负数跟 spec code 区分
                message=f"http {resp.status_code}: {resp.text[:512]}",
            )
        try:
            payload = resp.json()
        except ValueError as e:
            raise RPCError(code=-32700, message=f"malformed JSON: {e}") from e
        if not isinstance(payload, dict):
            raise RPCError(code=-32600, message=f"invalid JSON-RPC envelope: {type(payload).__name__}")
        if "error" in payload:
            raise RPCError.from_dict(payload["error"])
        if "result" not in payload:
            raise RPCError(code=-32600, message="missing 'result' in response envelope")
        result = payload["result"]
        if result is None:
            return None
        if out_class is dict or out_class is type(None):
            return result
        return _from_dict_to(result, out_class)


def _from_dict_to(data: Any, klass: type) -> Any:
    """dict → dataclass instance(支持 list[dataclass] 嵌套)。"""
    if not (is_dataclass(klass) and isinstance(data, dict)):
        return data
    # 局部 import 避免循环依赖
    from wau_sdk.mcp_dto import Artifact, Part, Task

    nested_types = {
        "Artifact": Artifact,
        "Part": Part,
        "Task": Task,
    }
    kwargs: dict[str, Any] = {}
    for f in klass.__dataclass_fields__.values():
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = str(f.type)
        # list[Artifact] / list[Part] 嵌套
        if ftype.startswith(("list[", "List[")):
            inner = ftype[5:-1].strip()
            if inner in nested_types and isinstance(value, list):
                kwargs[f.name] = [nested_types[inner](
                    **{k: v for k, v in item.items() if k in nested_types[inner].__dataclass_fields__}
                ) for item in value if isinstance(item, dict)]
            else:
                kwargs[f.name] = value
        else:
            kwargs[f.name] = value
    return klass(**kwargs)


# ────────────────────────────────────────────────────────
# AsyncMCPClient — async 版本
# ────────────────────────────────────────────────────────

class AsyncMCPClient:
    """MCP client async 版本(发 JSON-RPC 2.0 到 kernel /mcp)。

    用法::

        async with AsyncMCPClient("https://kernel.example.com", bearer_token="jwt") as mcp:
            card = await mcp.parse_agent_card(b'{"name":"Fox"}')
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        endpoint: str = "/mcp",
        user_agent: Optional[str] = None,
    ) -> None:
        if not base_url:
            raise ValueError("mcpclient: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint
        self._bearer_token = bearer_token
        self._user_agent = user_agent
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient()

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncMCPClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def set_bearer_token(self, token: str) -> None:
        self._bearer_token = token

    # ── 8 sync tool wrappers(async) ─────────────────────
    async def health_check(self, target: Any) -> HealthCheckResult:
        params = _build_tool_params(TOOL_HEALTH_CHECK, {"target": _normalize_target(target)})
        return await self._call_tool(params, HealthCheckResult)

    async def parse_agent_card(self, raw: Any) -> AgentCard:
        params = _build_parse_agent_card_params(raw)
        return await self._call_tool(params, AgentCard)

    async def send_message(self, target: Any, message: Message) -> Task:
        if message is None:
            raise ValueError("mcpclient: message is required")
        if not message.parts:
            raise ValueError("mcpclient: message.parts must have at least 1 item")
        params = _build_tool_params(
            TOOL_SEND_MESSAGE,
            {"target": _normalize_target(target), "message": _to_dict(message)},
        )
        return await self._call_tool(params, Task)

    async def get_task(self, target: Any, task_id: str) -> Task:
        if not task_id:
            raise ValueError("mcpclient: task_id is required")
        params = _build_tool_params(
            TOOL_GET_TASK, {"target": _normalize_target(target), "task_id": task_id}
        )
        return await self._call_tool(params, Task)

    async def list_tasks(self, target: Any, filter: Optional[ListTasksFilter] = None) -> ListTasksResult:
        args: dict[str, Any] = {"target": _normalize_target(target)}
        if filter is not None:
            args["filter"] = _to_dict(filter)
        params = _build_tool_params(TOOL_LIST_TASKS, args)
        return await self._call_tool(params, ListTasksResult)

    async def cancel_task(self, target: Any, task_id: str) -> Task:
        if not task_id:
            raise ValueError("mcpclient: task_id is required")
        params = _build_tool_params(
            TOOL_CANCEL_TASK, {"target": _normalize_target(target), "task_id": task_id}
        )
        return await self._call_tool(params, Task)

    async def create_task_push_notification_config(
        self, target: Any, config: PushConfig
    ) -> PushConfigResult:
        if config is None or not config.url:
            raise ValueError("mcpclient: config.url is required")
        params = _build_tool_params(
            TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG,
            {"target": _normalize_target(target), "config": _to_dict(config)},
        )
        return await self._call_tool(params, PushConfigResult)

    async def get_extended_agent_card(self, target: Any) -> ExtendedAgentCard:
        params = _build_tool_params(
            TOOL_GET_EXTENDED_AGENT_CARD, {"target": _normalize_target(target)}
        )
        return await self._call_tool(params, ExtendedAgentCard)

    # ── async JSON-RPC 2.0 dispatcher ──────────────────
    async def _call_tool(self, params: dict[str, Any], out_class: type) -> Any:
        envelope = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": params,
            "id": _generate_id(),
        }
        headers = build_headers(bearer_token=self._bearer_token, user_agent=self._user_agent)
        resp = await self._http.post(self._base_url + self._endpoint, json=envelope, headers=headers)
        return MCPClient._handle_response(resp, out_class)

    # ── SSE streaming tool wrappers (D89.A.6, per D89 SOP §2.1.1) ──
    async def stream_message(
        self,
        target: Any,
        message: Message,
        opts: Optional[Any] = None,
    ) -> Any:
        """调 stream_message tool 并开 SSE 长连接 (per D89.A.6 + D89 SOP §2.1.2)。

        流程:
          1. POST /mcp {tools/call, name=stream_message, arguments: {target, message, stream_options}}
             → 返 {stream_id, endpoint}
          2. GET <endpoint>?stream_id=<uuid>
             → 持续读 SSE event 推到 handle.events()

        返回的 StreamHandle 必须在不用时调 cancel()(或用 `async with` 自动清理)。

        Args:
            target: agent 标识(str 或 dict,跟 8 sync tool 一致)
            message: Message DTO (role + 至少 1 个 Part)
            opts: StreamOptions(可选),如 StreamOptions(include_history=True)

        Returns:
            StreamHandle(stream_id + events() + cancel())
        """
        # 本地 import 避免 mcp_streaming ↔ mcp_client 循环 import
        from wau_sdk.mcp_streaming import (
            StreamOptions,  # noqa: F401 - public re-export
            open_stream,
            _build_stream_arguments,
        )

        arguments = _build_stream_arguments(
            "stream_message",
            target,
            message=message,
            stream_options=opts,
        )
        return await open_stream(
            base_url=self._base_url,
            endpoint=self._endpoint,
            tool_name="stream_message",
            arguments=arguments,
            bearer_token=self._bearer_token,
            user_agent=self._user_agent,
            http=self._http,
        )

    async def subscribe_to_task(
        self,
        target: Any,
        task_id: str,
        opts: Optional[Any] = None,
    ) -> Any:
        """调 subscribe_to_task tool 并开 SSE 长连接 (per D89.A.6 + D89 SOP §2.1.2)。

        跟 stream_message 区别:参数是 task_id 而非 message。
        SSE frame 类型以 task_status / task_complete 为主(message/artifact 可选)。

        Args:
            target: agent 标识
            task_id: 订阅的 task UUID
            opts: StreamOptions(可选),如 StreamOptions(include_artifacts=True)

        Returns:
            StreamHandle(stream_id + events() + cancel())
        """
        from wau_sdk.mcp_streaming import (
            open_stream,
            _build_stream_arguments,
        )

        arguments = _build_stream_arguments(
            "subscribe_to_task",
            target,
            task_id=task_id,
            stream_options=opts,
        )
        return await open_stream(
            base_url=self._base_url,
            endpoint=self._endpoint,
            tool_name="subscribe_to_task",
            arguments=arguments,
            bearer_token=self._bearer_token,
            user_agent=self._user_agent,
            http=self._http,
        )