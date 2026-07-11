"""MCP SSE streaming client (wau-python-sdk v1.3.3, per D89.A.6).

D89.A.6 实装 (2026-07-11):2-phase MCP SSE 协议,
对齐 WAU-core-kernel internal/protocol/mcp/server.go handleSSE +
streamhub.go + handler.go StreamMessage / SubscribeToTask:

  Phase 1 — POST /mcp {tools/call, name: stream_message|subscribe_to_task, ...}
    response: {result: {stream_id, endpoint}}
  Phase 2 — GET /mcp/sse?stream_id=<uuid>
    SSE frames: open / message / artifact / task_status / task_complete /
                close / error

用法::

    async with AsyncMCPClient("https://kernel.example.com", bearer_token="jwt") as mcp:
        opts = StreamOptions(include_history=True)
        async with await mcp.stream_message("fox-agent", message, opts) as stream:
            async for ev in stream.events():
                if ev.type == "task_complete":
                    break

合规:
  - D60 additive (0 改老 8 sync tool)
  - D13 byte-equal (5 SDK 一致 snake_case JSON)
  - D78/D79/D80 (bearer token OAuth 2.0 identity_linking)
  - D89 SOP §2.1.3 (httpx.AsyncClient.stream + 自实现 SSE parser)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

from wau_sdk.mcp_auth import build_headers
from wau_sdk.mcp_errors import RPCError


# ────────────────────────────────────────────────────────
# Public types (跟 wau-go-sdk mcpclient/streaming.go byte-equal)
# ────────────────────────────────────────────────────────

# Frame types
FRAME_OPEN = "open"
FRAME_MESSAGE = "message"
FRAME_ARTIFACT = "artifact"
FRAME_TASK_STATUS = "task_status"
FRAME_TASK_COMPLETE = "task_complete"
FRAME_CLOSE = "close"
FRAME_ERROR = "error"

# Stream error code (跟 kernel mcp.ErrCodeMCPStreamClosed 镜像)
ERR_CODE_STREAM_CLOSED = -32003
MCP_STREAM_CLOSED_MSG = "stream_id not found or expired"


@dataclass
class StreamEvent:
    """从 /mcp/sse 收到的一个 SSE event。

    类型对齐 kernel server.go handleSSE + sseEncodeEvent:
      type: SSE event 字段值 (open/message/artifact/task_status/task_complete/close/error)
      stream_id / timestamp: 从 SSE data 字段提取(open frame 必填,其他可选)
      data: SSE data 行解析后的 dict (parsed JSON)
    """

    type: str
    stream_id: str = ""
    timestamp: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamOptions:
    """Stream session 可选配置(JSON tag snake_case 跟 kernel mcp.StreamOptions byte-equal)。

    nil = 不带 stream_options 字段。
    """

    include_history: bool = False
    include_artifacts: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转 dict 用于 JSON wire format。"""
        out: dict[str, Any] = {}
        if self.include_history:
            out["include_history"] = True
        if self.include_artifacts:
            out["include_artifacts"] = True
        return out


class StreamHandle:
    """开着的 stream 句柄(async iterator 模式,D89 SOP §2.1.1)。

    Usage::

        handle = await client.stream_message(target, message)
        try:
            async for ev in handle.events():
                ...
        finally:
            await handle.cancel()

    也支持 ``async with`` 自动 cancel。Cancel 是幂等的。
    """

    def __init__(
        self,
        stream_id: str,
        response: httpx.Response,
        expected_stream_id: str,
    ) -> None:
        self._stream_id = stream_id
        self._response = response
        self._expected_stream_id = expected_stream_id
        self._queue: asyncio.Queue[StreamEvent | BaseException | None] = (
            asyncio.Queue(maxsize=64)
        )
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._done = asyncio.Event()
        self._reader_task: Optional[asyncio.Task[None]] = None

    def _attach_reader_task(self, task: asyncio.Task[None]) -> None:
        """注入后台 reader task(由 open_stream() 在 handle 构造后调用)。"""
        self._reader_task = task

    @property
    def stream_id(self) -> str:
        """server 分配的 stream UUID。"""
        return self._stream_id

    @property
    def done(self) -> asyncio.Event:
        """stream 完全关闭时 set 的事件。"""
        return self._done

    def _enqueue_event(self, ev: StreamEvent) -> None:
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            pass

    def _enqueue_error(self, err: BaseException) -> None:
        try:
            self._queue.put_nowait(err)
        except asyncio.QueueFull:
            pass

    def _signal_close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def events(self) -> AsyncIterator[StreamEvent]:
        """async iterator:yield SSE events as they arrive。

        流关闭时 iterator 自动退出(StopAsyncIteration)。中途异常会抛
        RPCError 或 asyncio.CancelledError (per cancel 原因)。
        """
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            assert isinstance(item, StreamEvent)
            yield item

    async def cancel(self) -> None:
        """主动关闭 stream + close queue + cancel in-flight HTTP response。幂等。"""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._signal_close()
            if self._reader_task is not None:
                self._reader_task.cancel()
                try:
                    await asyncio.shield(self._reader_task)
                except (asyncio.CancelledError, BaseException):
                    pass
            try:
                await self._response.aclose()
            except Exception:
                pass
            self._done.set()

    async def __aenter__(self) -> "StreamHandle":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.cancel()


# ────────────────────────────────────────────────────────
# SSE parser (自实现,per W3-launch-SOP §3.3:httpx_sse 未 ship)
# ────────────────────────────────────────────────────────

async def _read_sse_frames(
    handle: StreamHandle,
    response: httpx.Response,
    expected_stream_id: str,
) -> None:
    """后台 task:读 SSE frames → push StreamEvent / Exception / None 到 handle queue。

    镜像 wau-go-sdk mcpclient.parseSSEStream:
      - event: 字段提取 event type
      - data:  字段累积多行 → JSON parse
      - id/retry: ignore (W3 不重连)
      - ":..." comment line: ignore
      - blank line: frame boundary
    """
    event_type = ""
    data_lines: list[str] = []
    try:
        async for raw_line in response.aiter_lines():
            line = "" if raw_line is None else str(raw_line)
            if line == "":
                if event_type or data_lines:
                    _dispatch_sse_frame(handle, event_type, data_lines, expected_stream_id)
                    event_type = ""
                    data_lines = []
                continue
            if line.startswith(":"):
                continue
            field_name, sep, value = line.partition(":")
            if not sep:
                continue
            if value.startswith(" "):
                value = value[1:]
            if field_name == "event":
                event_type = value
            elif field_name == "data":
                data_lines.append(value)
        # EOF:可能最后有未 dispatch 的 frame
        if event_type or data_lines:
            _dispatch_sse_frame(handle, event_type, data_lines, expected_stream_id)
        handle._signal_close()
        handle._done.set()
    except asyncio.CancelledError:
        # cancel() 已经 set _done.
        raise
    except Exception as e:
        handle._enqueue_error(e)
        handle._done.set()


def _dispatch_sse_frame(
    handle: StreamHandle,
    event_type: str,
    data_lines: list[str],
    expected_stream_id: str,
) -> None:
    """拼 frame + 解析 data JSON + 投递到 handle queue。

    数据流:
      close frame → push None sentinel (iterator exit)
      error frame → push RPCError (iterator raise)
      普通 frame  → push StreamEvent
    """
    data_str = "\n".join(data_lines)

    if event_type == FRAME_CLOSE:
        handle._signal_close()
        return

    if event_type == FRAME_ERROR:
        try:
            err_dict = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            err_dict = {}
        rpc_err: BaseException
        if isinstance(err_dict, dict):
            rpc_err = RPCError.from_dict(err_dict)
        else:
            rpc_err = RPCError(code=ERR_CODE_STREAM_CLOSED, message=str(data_str))
        handle._enqueue_error(rpc_err)
        return

    if data_str == "":
        return  # empty data frame: skip per SSE spec

    try:
        data: Any = json.loads(data_str)
    except json.JSONDecodeError as e:
        handle._enqueue_error(
            RPCError(code=-32700, message=f"malformed sse data line: {e}")
        )
        return

    if not isinstance(data, dict):
        data = {"value": data}

    stream_id_val = data.get("stream_id")
    stream_id = str(stream_id_val) if stream_id_val else ""
    timestamp_val = data.get("timestamp")
    timestamp = str(timestamp_val) if timestamp_val else ""

    if stream_id and expected_stream_id and stream_id != expected_stream_id:
        handle._enqueue_error(
            RPCError(
                code=ERR_CODE_STREAM_CLOSED,
                message=(
                    f"stream_id mismatch: expected {expected_stream_id!r}, "
                    f"got {stream_id!r}"
                ),
            )
        )
        return

    handle._enqueue_event(StreamEvent(
        type=event_type or "",
        stream_id=stream_id or expected_stream_id,
        timestamp=timestamp,
        data=data,
    ))


# ────────────────────────────────────────────────────────
# Internal: 2-phase stream opener (跟 wau-go-sdk mcpclient.openStream 镜像)
# ────────────────────────────────────────────────────────

@dataclass
class _StreamOpenResult:
    """POST stream_message / subscribe_to_task 返回 envelope。"""
    stream_id: str
    endpoint: str


def _normalize_target_local(target: Any) -> Any:
    """target 接受 string(agent name) 或 dict(AgentRef),统一为 dict。"""
    if target is None:
        raise ValueError("mcpclient: target is required")
    if isinstance(target, str):
        return {"name": target}
    if isinstance(target, dict):
        return target
    raise TypeError(f"mcpclient: target must be str or dict, got {type(target).__name__}")


def _to_dict_local(obj: Any) -> Any:
    """递归转 dataclass / list / dict 到 plain dict (JSON-serializable)。"""
    from dataclasses import asdict, is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _to_dict_local(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict_local(v) for v in obj]
    return obj


def _build_stream_arguments(
    tool_name: str,
    target: Any,
    message: Optional[Any] = None,
    task_id: Optional[str] = None,
    stream_options: Optional[StreamOptions] = None,
) -> dict[str, Any]:
    """构造 stream_message / subscribe_to_task 的 arguments。"""
    arguments: dict[str, Any] = {"target": _normalize_target_local(target)}
    if tool_name == "stream_message":
        if message is None:
            raise ValueError("mcpclient: message is required")
        if not getattr(message, "parts", None):
            raise ValueError("mcpclient: message.parts must have at least 1 item")
        arguments["message"] = _to_dict_local(message)
    elif tool_name == "subscribe_to_task":
        if not task_id:
            raise ValueError("mcpclient: task_id is required")
        arguments["task_id"] = task_id
    else:
        raise ValueError(f"mcpclient: unknown streaming tool {tool_name!r}")
    if stream_options is not None:
        arguments["stream_options"] = stream_options.to_dict()
    return arguments


def _resolve_endpoint_url(base_url: str, endpoint: str, stream_id: str) -> str:
    """拼 endpoint URL (可能 server 返的是完整 URL 也可能相对路径)。"""
    url = endpoint
    if url.startswith("http://") or url.startswith("https://"):
        pass
    elif url.startswith("/"):
        url = base_url.rstrip("/") + url
    else:
        url = base_url.rstrip("/") + "/" + url
    if "stream_id=" not in url:
        sep = "&" if "?" in url else "?"
        url = url + sep + "stream_id=" + stream_id
    return url


async def _post_stream_open(
    base_url: str,
    endpoint: str,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: Optional[str],
    user_agent: Optional[str],
    http: httpx.AsyncClient,
) -> _StreamOpenResult:
    """Phase 1:POST /mcp 启动 stream,获取 stream_id + endpoint。"""
    from wau_sdk.mcp_client import _generate_id

    envelope = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": _generate_id(),
    }
    headers = build_headers(bearer_token=bearer_token, user_agent=user_agent)
    resp = await http.post(
        base_url.rstrip("/") + endpoint, json=envelope, headers=headers,
    )
    payload = await _parse_json_envelope(resp)
    if "error" in payload:
        raise RPCError.from_dict(payload["error"])
    if "result" not in payload:
        raise RPCError(code=-32600, message="missing 'result' in stream open envelope")
    result = payload["result"]
    if not isinstance(result, dict):
        raise RPCError(
            code=-32600,
            message=f"invalid stream open result: {type(result).__name__}",
        )
    stream_id = result.get("stream_id", "")
    endpoint_path = result.get("endpoint", "")
    if not stream_id or not endpoint_path:
        raise RPCError(
            code=-32600,
            message=f"stream open missing stream_id/endpoint: {result!r}",
        )
    return _StreamOpenResult(stream_id=str(stream_id), endpoint=str(endpoint_path))


async def _parse_json_envelope(resp: httpx.Response) -> dict[str, Any]:
    """Parse JSON-RPC 2.0 envelope (跟 MCPClient._handle_response 镜像)。"""
    if resp.status_code >= 400:
        try:
            payload = resp.json()
            if isinstance(payload, dict) and "error" in payload:
                raise RPCError.from_dict(payload["error"])
        except (ValueError, RPCError) as e:
            if isinstance(e, RPCError):
                raise
        raise RPCError(
            code=resp.status_code * -1,
            message=f"http {resp.status_code}: {resp.text[:512]}",
        )
    try:
        payload = resp.json()
    except ValueError as e:
        raise RPCError(code=-32700, message=f"malformed JSON: {e}") from e
    if not isinstance(payload, dict):
        raise RPCError(
            code=-32600,
            message=f"invalid JSON-RPC envelope: {type(payload).__name__}",
        )
    return payload


async def open_stream(
    base_url: str,
    endpoint: str,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: Optional[str],
    user_agent: Optional[str],
    http: httpx.AsyncClient,
) -> StreamHandle:
    """打开一个 MCP SSE stream (Phase 1 POST + Phase 2 GET SSE + 后台 reader)。"""
    # Phase 1: POST stream open
    open_result = await _post_stream_open(
        base_url, endpoint, tool_name, arguments, bearer_token, user_agent, http,
    )

    # Phase 2: GET /mcp/sse?stream_id=...
    sse_url = _resolve_endpoint_url(base_url, open_result.endpoint, open_result.stream_id)
    headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "User-Agent": user_agent or "wau-python-sdk/mcpclient/v1.3.3",
    }
    if bearer_token:
        headers["Authorization"] = "Bearer " + bearer_token

    request = http.build_request("GET", sse_url, headers=headers)
    response = await http.send(request, stream=True)
    try:
        if response.status_code == 401:
            await response.aclose()
            raise RPCError(
                code=-401,
                message="http 401: unauthorized (bearer token rejected)",
            )
        if response.status_code == 404:
            await response.aclose()
            raise RPCError(
                code=ERR_CODE_STREAM_CLOSED,
                message=f"{MCP_STREAM_CLOSED_MSG}: {open_result.stream_id}",
            )
        if response.status_code >= 400:
            body_text = await response.aread()
            await response.aclose()
            raise RPCError(
                code=response.status_code * -1,
                message=f"http {response.status_code}: {body_text.decode('utf-8', 'ignore')[:512]}",
            )

        # 建立 StreamHandle + 启动 reader task
        handle = StreamHandle(
            stream_id=open_result.stream_id,
            response=response,
            expected_stream_id=open_result.stream_id,
        )
        reader_task = asyncio.create_task(
            _read_sse_frames(handle, response, open_result.stream_id)
        )
        handle._attach_reader_task(reader_task)
        return handle
    except BaseException:
        try:
            await response.aclose()
        except Exception:
            pass
        raise
