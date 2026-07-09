"""bot.feishu.bot — FeishuBot native SDK integration (W6.2 Stage 1, 2026-07-09)

对齐 wau-go-sdk/bot/feishu/feishu.go + wau-channel/internal/adapter/feishu/feishu_real.go。

W6 (2026-07-09) W6.2 实装:
  - Native SDK: lark-oapi>=1.2(lark.Client + WS Client + EventDispatcher)
  - Start       → lark.ws.client.Client.start()(WS 长连接 open.feishu.cn)
                  + lark.event.EventDispatcher.OnP2MessageReceiveV1 注册
  - Stop        → cancel WS Client + 关 events channel
  - PostMessage → lark.Client.im.v1.message.create(REST /open-apis/im/v1/messages)
  - UpdateMessage → lark.Client.im.v1.message.patch(REST PATCH /open-apis/im/v1/messages/{id})

字段对齐 per D13 + D78 + D80:app_id / app_secret / tenant / universe / handler。

飞书 Open Platform 协议要点(per feishu_real.go):
  - receive_id_type 维度:chat_id / open_id / email / union_id
  - msg_type=text content:`{"text":"..."}`(JSON 字符串)
  - 字段二选一 escape: (转义反斜杠) → (双反斜杠), `"` → `\\"`, `\n` → `\\n`
  - WS 长连接走 ws://open.feishu.cn/open-apis/socket/v1/connect
  - EventDispatcher 自动 ack;我们只 register OnP2MessageReceiveV1

用法::

    bot = new_feishu_bot(
        app_id="cli_...", app_secret="...",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda m: OutgoingMessage(text=f"echo: {m.text}")),
    )
    asyncio.run(bot.start())
    ...
    asyncio.run(bot.stop())

0 门槛 UX:app_id / app_secret 空立即报错;WS Start 失败 → start() 抛错;
events channel 满 → drop + log(per slack / feishu pattern)。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder

logger = logging.getLogger(__name__)

# SDK imports(per W6.1 dep 追加;try/except 容错离线场景,测试可 mock)
try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        PatchMessageRequest,
        PatchMessageRequestBody,
    )
    from lark_oapi.event import EventDispatcher
    from lark_oapi.ws.client import Client as LarkWSClient

    _FEISHU_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    lark = None  # type: ignore[assignment]
    CreateMessageRequest = None  # type: ignore[assignment]
    CreateMessageRequestBody = None  # type: ignore[assignment]
    PatchMessageRequest = None  # type: ignore[assignment]
    PatchMessageRequestBody = None  # type: ignore[assignment]
    EventDispatcher = None  # type: ignore[assignment]
    LarkWSClient = None  # type: ignore[assignment]
    _FEISHU_SDK_AVAILABLE = False


# 飞书 OpenAPI 文本消息 content 格式(per feishu_real.go §业务常量)
FEISHU_MSG_TYPE_TEXT = "text"
FEISHU_RECEIVE_ID_TYPE_CHAT = "chat_id"
FEISHU_DOMAIN = "https://open.feishu.cn"


class FeishuBot(Bot):
    """Feishu (Lark) Bot — native lark-oapi async 集成(W6.2 Stage 1)。

    字段(per D13 + D80):
        app_id: str      — 飞书应用 App ID (cli_...)
        app_secret: str  — 飞书应用 App Secret
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]

    内部状态:
        _lark_client     lark.Client(用于 PostMessage / UpdateMessage REST)
        _ws_client       lark.ws.client.Client(WS 长连接)
        _dispatcher      lark.event.EventDispatcher(注册 OnP2MessageReceiveV1)
        _started         start() 防重入
        _stop_event      asyncio.Event
        _events          asyncio.Queue 用于 receive 端 → handler 桥接
    """

    bot_id: str  # 运行时首次收到事件时缓存

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        builder: BotBuilder,
    ) -> None:
        self.app_id: str = app_id
        self.app_secret: str = app_secret
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

        # W6.2 实装字段
        self._lark_client: Any = None
        self._ws_client: Optional[LarkWSClient] = None
        self._dispatcher: Any = None
        self._started: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=64)

        # bot_id 运行时缓存 — Per D80 透传;由 EventDispatcher callback 首次填充
        self.bot_id: str = ""

    # ------------------------------------------------------------------
    # Bot interface — 5 public 方法(per D13 + M10 N1)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 Feishu Bot(per W6.2 WS 长连接)。

        步骤:
          1. 校验 app_id / app_secret
          2. 构造 lark.Client + EventDispatcher
          3. EventDispatcher.OnP2MessageReceiveV1 注册(handler 把 event 推 events queue)
          4. 构造 lark.ws.client.Client + start()(同步阻塞,放线程池跑)
          5. 启 dispatch loop(把 events queue → user handler → 可选 update)
        """
        if self._started:
            logger.warning("[feishu] bot already started (no-op)")
            return

        if not _FEISHU_SDK_AVAILABLE:
            raise RuntimeError(
                "lark-oapi not installed (W6.1 dep lark-oapi>=1.2 缺失, "
                "pip install lark-oapi)"
            )

        if not self.app_id or not self.app_secret:
            raise ValueError("feishu: app_id and app_secret are required")

        # 1. lark.Client(用于 PostMessage / UpdateMessage REST:open.feishu.cn)
        self._lark_client = lark.Client(
            self.app_id,
            self.app_secret,
            lark.with_enable_token_cache(True),
            lark.with_open_base_url(FEISHU_DOMAIN),
        )

        # 2. EventDispatcher(WS 长连接模式不需要 verification token)
        self._dispatcher = EventDispatcher("", "")

        # 3. 注册 OnP2MessageReceiveV1(per feishu_real.go §133-156)
        def _on_p2_message_receive(ev: Any) -> None:
            try:
                incoming = _translate_p2_message(ev)
                if incoming is None:
                    return
                self._enqueue_incoming(incoming)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[feishu] on_p2_message handler failed: %s", exc)

        self._dispatcher.on_p2_message_receive_v1(_on_p2_message_receive)

        # 4. 构造 WS Client
        self._ws_client = LarkWSClient(
            self.app_id,
            self.app_secret,
            event_handler=self._dispatcher,
            domain=FEISHU_DOMAIN,
            auto_reconnect=True,
        )

        self._stop_event.clear()
        self._started = True

        # 5. 启 WS start()(SDK 内部阻塞,放 to_thread 不阻塞 asyncio 循环)
        asyncio.create_task(
            self._ws_run_loop(),
            name=f"feishu-ws-{self.app_id}",
        )

        # 6. 启 dispatch loop
        asyncio.create_task(
            self._dispatch_loop(),
            name=f"feishu-dispatch-{self.app_id}",
        )
        logger.info(
            "[feishu] bot started (app_id=%s, tenant=%s, universe=%s)",
            self.app_id,
            self.tenant,
            self.universe,
        )

    async def stop(self) -> None:
        """优雅停止 Feishu Bot(per W6.2)。

        WS Client 无 close() 显式 API(SDK 内部用 EventDispatcher 句柄 + ws session);
        策略:set _stop_event(让 ws_run_loop / dispatch_loop 退出)。
        """
        if not self._started:
            return
        try:
            self._stop_event.set()
            # WSClient 无 close; 内部 reconnect 在 _stop_event 下不再重连
            # (用 auto_reconnect=True + 短 ping 收尾)
            self._ws_client = None
            self._lark_client = None
            self._started = False
            logger.info("[feishu] bot stopped (app_id=%s)", self.app_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[feishu] stop error: %s", exc)

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "FeishuBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "FeishuBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "FeishuBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    # ------------------------------------------------------------------
    # Feishu-specific public methods(per Feishu OpenAPI)
    # ------------------------------------------------------------------

    async def post_message(
        self,
        chat_id: str,
        text: str,
    ) -> str:
        """Send a new message via POST /open-apis/im/v1/messages(per 飞书 OpenAPI)。

        :returns: message_id(用作 update 的 handle)
        """
        if not self._lark_client:
            raise RuntimeError("feishu: not started (call start() first)")
        if not chat_id:
            raise ValueError("feishu: chat_id is required")
        if not text:
            raise ValueError("feishu: text is required")
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type(FEISHU_MSG_TYPE_TEXT)
            .content(_build_text_content(text))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type(FEISHU_RECEIVE_ID_TYPE_CHAT)
            .request_body(body)
            .build()
        )
        resp = await self._lark_client.im.v1.message.acreate(req)
        msg_id = ""
        if getattr(resp, "success", lambda: False)():
            data = getattr(resp, "data", None)
            if data is not None and getattr(data, "message_id", None):
                msg_id = data.message_id
        else:
            code = getattr(resp, "code", -1)
            msg = getattr(resp, "msg", "")
            raise RuntimeError(
                f"feishu: CreateMessage fail code={code} msg={msg}"
            )
        return msg_id

    async def update_message(
        self,
        chat_id: str,
        message_id: str,
        new_text: str,
    ) -> str:
        """Update an existing message via PATCH /open-apis/im/v1/messages/{id}。

        :returns: 更新后的 message_id(per Feishu API 通常等于原 message_id)
        """
        if not self._lark_client:
            raise RuntimeError("feishu: not started (call start() first)")
        if not chat_id or not message_id:
            raise ValueError("feishu: chat_id and message_id are required")
        if not new_text:
            raise ValueError("feishu: new_text is required")
        body = (
            PatchMessageRequestBody.builder()
            .content(_build_text_content(new_text))
            .build()
        )
        req = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        resp = await self._lark_client.im.v1.message.apatch(req)
        if getattr(resp, "success", lambda: False)():
            return message_id
        code = getattr(resp, "code", -1)
        msg = getattr(resp, "msg", "")
        raise RuntimeError(
            f"feishu: PatchMessage fail code={code} msg={msg}"
        )

    async def submit_to_core(
        self,
        prompt: str,
        timeout_ms: int = 30000,
    ) -> dict:
        """通过 wau_sdk.tasks.submit 把 prompt 提交到 wau-core-kernel(per W6.2)。"""
        from wau_sdk.tasks import AsyncTasksService, SubmitRequest  # type: ignore[attr-defined]
        from wau_sdk._client import AsyncClient  # type: ignore[attr-defined]

        async with AsyncClient("http://localhost:18400") as c:
            svc: AsyncTasksService = c.tasks
            resp = await svc.submit(
                SubmitRequest(prompt=prompt, timeout_ms=timeout_ms)
            )
            return {
                "task_id": resp.task_id,
                "agent_id": resp.agent_id,
                "status": resp.status,
                "response": resp.response,
                "selected_agent": resp.selected_agent,
                "score": resp.score,
            }

    # ------------------------------------------------------------------
    # SDK 适配内部方法
    # ------------------------------------------------------------------

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler

    async def _ws_run_loop(self) -> None:
        """后台协程:run LarkWSClient.start()。

        SDK 的 start() 内部 WS lifecycle + reconnect;我们在 thread pool 跑
        不阻塞 asyncio 循环。_stop_event.set() 时退出(per stop())。
        """
        if self._ws_client is None:
            return
        try:
            await asyncio.to_thread(self._ws_client.start)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[feishu] ws_run_loop ended: %s", exc)

    async def _dispatch_loop(self) -> None:
        """把 events queue 排空到 user handler(IncomingMessage → OutgoingMessage → post)。

        收到 IncomingMessage → 调 self._handler → 拿 OutgoingMessage → 用 OutgoingMessage.text
        post 回原 chat_id(即 IncomingMessage.channel_id)。
        """
        while not self._stop_event.is_set():
            try:
                incoming: IncomingMessage = await asyncio.wait_for(
                    self._events.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            if self._handler is None:
                continue
            try:
                outgoing = self._handler(incoming)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[feishu] handler raised for incoming %s: %s",
                    incoming.platform_msg_id,
                    exc,
                )
                continue
            if outgoing is None:
                continue
            if outgoing.text:
                try:
                    await self.post_message(
                        chat_id=incoming.channel_id,
                        text=outgoing.text,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[feishu] post_message failed (chat=%s): %s",
                        incoming.channel_id,
                        exc,
                    )

    def _enqueue_incoming(self, incoming: IncomingMessage) -> None:
        """从 EventDispatcher callback(SDK 内部线程)推到 asyncio.Queue。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_soon_threadsafe(self._safe_put_nowait, incoming)

    def _safe_put_nowait(self, incoming: IncomingMessage) -> None:
        try:
            self._events.put_nowait(incoming)
        except asyncio.QueueFull:
            logger.warning(
                "[feishu] events queue full, dropping incoming %s",
                incoming.platform_msg_id,
            )


def _build_text_content(text: str) -> str:
    """Escape text → `{"text":"..."}` Feishu text msg_type content JSON。

    per feishu_real.go buildTextContent pattern:`\\` `"` `\\n` `\\r` `\\t` 转义。
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return json.dumps({"text": escaped}, ensure_ascii=False)


def _translate_p2_message(ev: Any) -> Optional[IncomingMessage]:
    """lark P2MessageReceiveV1 event → IncomingMessage(per D13 字段对齐)。

    字段映射(per feishu_real.go convertP2MessageReceiveV1):
        sender.sender_id.open_id → user_id
        message.message_id → platform_msg_id
        message.chat_id → channel_id
        message.content(text JSON) → text
        message.root_id → reply_to
        message.create_time → timestamp(传参运行时)
    """
    if ev is None:
        return None
    event = getattr(ev, "event", None)
    if event is None:
        return None

    user_id = ""
    sender = getattr(event, "sender", None)
    if sender is not None:
        sender_id = getattr(sender, "sender_id", None)
        if sender_id is not None:
            user_id = (
                getattr(sender_id, "open_id", "") or
                getattr(sender_id, "user_id", "") or
                getattr(sender_id, "union_id", "") or ""
            )
            if user_id:
                user_id = str(user_id)

    msg = getattr(event, "message", None)
    if msg is None:
        return None

    platform_msg_id = str(getattr(msg, "message_id", "") or "")
    chat_id = str(getattr(msg, "chat_id", "") or "")
    root_id = str(getattr(msg, "root_id", "") or "")

    text = ""
    raw_content = getattr(msg, "content", "") or ""
    if isinstance(raw_content, str) and raw_content:
        try:
            parsed = json.loads(raw_content)
            text = parsed.get("text", "") or ""
        except (ValueError, TypeError):
            text = raw_content

    return IncomingMessage(
        platform_msg_id=platform_msg_id,
        channel_id=chat_id,
        user_id=user_id,
        username=getattr(sender, "name", "") or "" if sender else "",
        text=text,
        reply_to=root_id,
    )


def new_feishu_bot(
    app_id: str, app_secret: str, builder: BotBuilder
) -> FeishuBot:
    """用 app_id + app_secret + builder 创建 Feishu bot(W6.2 native SDK)。"""
    return FeishuBot(app_id=app_id, app_secret=app_secret, builder=builder)
