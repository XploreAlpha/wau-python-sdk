"""bot.dingtalk.bot — DingTalkBot native SDK integration (W6.2 Stage 1, 2026-07-09)

对齐 wau-go-sdk/bot/dingtalk/dingtalk.go + wau-channel/internal/adapter/dingtalk/dingtalk_real.go。

W6 (2026-07-09) W6.2 实装:
  - Native SDK: dingtalk-stream>=1.0
    主要 class: DingTalkStreamClient / Credential / AsyncChatbotHandler
  - Start       → DingTalkStreamClient.start()(websocket 长连接)
                  + register_chatbot_handler(异步 / 同步 handler)
  - Stop        → DingTalkStreamClient.stop()
  - PostMessage → webhook_reply(SimpleReplyText)via cached sessionWebhook
  - UpdateMessage → DingTalk bot 模型 Stream Mode 无真 update API;
                   语义:reply by cached sessionWebhook(per dingtalk_real.go §196)

字段对齐 per D13 + D78 + D80:app_key / app_secret / tenant / universe / handler。

钉钉 Stream Mode callback 协议(per dingtalk_real.go §onChatBotMessage):
  - chatbot callback 推 data 含:MsgId / ConversationId / SessionWebhook /
    ConversationType / SenderStaffId / SenderId / SenderNick / Text /
    AtUsers / CreateAt
  - 缓存 sessionWebhook(per ConversationId)→ PostMessage / UpdateMessage 用
  - botID 通过 callback data.SenderStaffId / SenderId 拿(运行时首次填充)

DingTalk bot 模型限制(per dingtalk_real.go §196-201):
  - 没有 "update message" API,只 reply-by-webhook
  - UpdateMessage 在 DingTalk 语义下 = reply with new text
  - 返回 DingtalkMessage.MessageID 保留 = 原传入 messageID (caller-side 关联键)

用法::

    bot = new_dingtalk_bot(
        app_key="...", app_secret="...",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda m: OutgoingMessage(text=f"echo: {m.text}")),
    )
    asyncio.run(bot.start())
    ...
    asyncio.run(bot.stop())

0 门槛 UX:app_key / app_secret 空立即报错;sessionWebhook 未缓存 → PostMessage 抛错
(需先收到 incoming event);events channel 满 → drop + log。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder

logger = logging.getLogger(__name__)

# SDK 导入(per W6.1 dep 追加)。DingTalk Stream Mode SDK 暴露:
#   DingTalkStreamClient / Credential / ChatbotHandler / ChatbotMessage
#   AsyncChatbotHandler(async 版本,W6.2 用这个避开同步阻塞 asyncio)
try:
    from dingtalk_stream import (
        AsyncChatbotHandler,
        ChatbotMessage,
        Credential,
        DingTalkStreamClient,
    )

    _DINGTALK_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    AsyncChatbotHandler = None  # type: ignore[assignment,misc]
    ChatbotMessage = None  # type: ignore[assignment,misc]
    Credential = None  # type: ignore[assignment,misc]
    DingTalkStreamClient = None  # type: ignore[assignment,misc]
    _DINGTALK_SDK_AVAILABLE = False


# DingTalkRealClientEventBuffer(per dingtalk_real.go §40 realClientEventBuffer)
DINGTALK_EVENT_BUFFER = 16


class DingTalkBot(Bot):
    """DingTalk Bot — native dingtalk-stream async 集成(W6.2 Stage 1)。

    字段(per D13 + D80):
        app_key: str
        app_secret: str
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]

    内部状态:
        _stream_client  DingTalkStreamClient(websocket 长连接)
        _credential     Credential(app_key + app_secret)
        _started        start() 防重入
        _stop_event     asyncio.Event
        _events         asyncio.Queue
        _webhooks       conversationID → sessionWebhook URL 缓存
                        (per dingtalk_real.go §56-60 webhooks map)
    """

    bot_id: str

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        builder: BotBuilder,
    ) -> None:
        self.app_key: str = app_key
        self.app_secret: str = app_secret
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

        # W6.2 实装字段
        self._stream_client: Optional[DingTalkStreamClient] = None
        self._credential: Optional[Credential] = None
        self._started: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=DINGTALK_EVENT_BUFFER)

        # sessionWebhook 缓存(per dingtalk_real.go §56 webhooks map,thread-safe)
        self._webhooks: dict[str, str] = {}
        self._webhooks_lock: asyncio.Lock = asyncio.Lock()

        # botID 运行时缓存 — by callback data.SenderStaffId(per D80)
        self.bot_id: str = ""

    # ------------------------------------------------------------------
    # Bot interface — 5 public 方法(per D13 + M10 N1)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 DingTalk Bot(per W6.2 Stream Mode websocket 长连接)。

        步骤:
          1. 校验 app_key / app_secret
          2. 构造 Credential + DingTalkStreamClient
          3. 注册 AsyncChatbotHandler → callback 推 events queue + 缓存 sessionWebhook
          4. 后台 task 跑 stream_client.start()(SDK 内部 WS 长连接)
          5. 启 dispatch loop(events queue → user handler → reply)
        """
        if self._started:
            logger.warning("[dingtalk] bot already started (no-op)")
            return

        if not _DINGTALK_SDK_AVAILABLE:
            raise RuntimeError(
                "dingtalk-stream not installed (W6.1 dep dingtalk-stream>=1.0 缺失, "
                "pip install dingtalk-stream)"
            )

        if not self.app_key or not self.app_secret:
            raise ValueError("dingtalk: app_key and app_secret are required")

        # 1. 构造 Credential + StreamClient
        self._credential = Credential(self.app_key, self.app_secret)
        self._stream_client = DingTalkStreamClient(self._credential)

        # 2. 注册 AsyncChatbotHandler(per dingtalk_real.go §87 RegisterChatBotCallbackRouter)
        async def _on_chatbot_message(event: Any) -> None:
            """Async chatbot handler:把 SDK callback 翻译成 IncomingMessage。

            event:dingtalk_stream.ChatbotMessage 实例(per SDK doc)
            字段:msgid / conversationId / conversationType / sessionWebhook /
                  senderNick / senderId / senderStaffId / text(content str)/atUsers
            """
            try:
                # 缓存 sessionWebhook(供 PostMessage 用)
                conv_id = str(
                    getattr(event, "conversation_id", "") or
                    getattr(event, "conversationId", "") or
                    ""
                )
                webhook = str(
                    getattr(event, "session_webhook", "") or
                    getattr(event, "sessionWebhook", "") or
                    ""
                )
                if conv_id and webhook:
                    async with self._webhooks_lock:
                        self._webhooks[conv_id] = webhook

                msg_id = str(
                    getattr(event, "msgid", "") or
                    getattr(event, "msg_id", "") or ""
                )
                sender_staff = str(
                    getattr(event, "sender_staff_id", "") or
                    getattr(event, "senderStaffId", "") or
                    ""
                )
                sender_id = str(
                    getattr(event, "sender_id", "") or
                    getattr(event, "senderId", "") or
                    ""
                )
                sender_nick = str(
                    getattr(event, "sender_nick", "") or
                    getattr(event, "senderNick", "") or
                    ""
                )
                # bot_id 透传(D80):用 sender_staff / sender_id 缓存
                if sender_staff and not self.bot_id:
                    self.bot_id = sender_staff
                elif sender_id and not self.bot_id:
                    self.bot_id = sender_id

                # text(content 是 dict {"content": "..."} 或 str)
                text_value = ""
                text_raw = getattr(event, "text", None)
                if text_raw is None:
                    text_raw = getattr(event, "content", None)
                if isinstance(text_raw, dict):
                    text_value = str(text_raw.get("content", "") or "")
                elif isinstance(text_raw, str):
                    text_value = text_raw

                incoming = IncomingMessage(
                    platform_msg_id=msg_id,
                    channel_id=conv_id,
                    user_id=sender_staff or sender_id,
                    username=sender_nick,
                    text=text_value,
                    reply_to="",
                )
                self._enqueue_incoming(incoming)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[dingtalk] on_chatbot_message handler failed: %s",
                    exc,
                )

        try:
            self._stream_client.register_async_chatbot_handler(
                AsyncChatbotHandler(
                    on_message=_on_chatbot_message,
                ),
            )
        except AttributeError:
            # SDK 版本不支持 register_async_chatbot_handler → 退同步路径
            # 提供 asyncio.run_coroutine_threadsafe 桥
            def _sync_handler(event: Any) -> None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                asyncio.run_coroutine_threadsafe(
                    _on_chatbot_message(event), loop
                )

            try:
                self._stream_client.register_chatbot_handler(  # type: ignore[attr-defined]
                    _sync_handler,
                )
            except (AttributeError, TypeError) as exc:
                raise RuntimeError(
                    f"dingtalk: register_chatbot_handler failed: {exc}"
                ) from exc

        self._stop_event.clear()
        self._started = True

        # 3. 启 SDK stream(内部 WS 长连接;非阻塞)
        asyncio.create_task(
            self._stream_run_loop(),
            name=f"dingtalk-stream-{self.app_key}",
        )

        # 4. 启 dispatch loop
        asyncio.create_task(
            self._dispatch_loop(),
            name=f"dingtalk-dispatch-{self.app_key}",
        )
        logger.info(
            "[dingtalk] bot started (app_key=%s, tenant=%s, universe=%s)",
            self.app_key,
            self.tenant,
            self.universe,
        )

    async def stop(self) -> None:
        """优雅停止 DingTalk Bot(per W6.2)。"""
        if not self._started:
            return
        try:
            self._stop_event.set()
            if self._stream_client is not None:
                try:
                    self._stream_client.stop()  # sync per SDK doc
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[dingtalk] stream_client.stop error: %s", exc)
            self._stream_client = None
            self._credential = None
            self._started = False
            logger.info("[dingtalk] bot stopped (app_key=%s)", self.app_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dingtalk] stop error: %s", exc)

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "DingTalkBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "DingTalkBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "DingTalkBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    # ------------------------------------------------------------------
    # DingTalk-specific public methods(per 钉钉 bot 模型)
    # ------------------------------------------------------------------

    async def post_message(
        self,
        conversation_id: str,
        text: str,
        message_id: str = "",
    ) -> str:
        """Reply via cached sessionWebhook(per DingTalk Stream bot 模型)。

        对齐 dingtalk_real.go §172 PostMessage — 必须先收到 incoming event 缓存
        sessionWebhook 才能 reply。

        :returns: 占位 message_id(per dingtalk_real.go §192 空给 caller-side)
        """
        if not conversation_id:
            raise ValueError("dingtalk: conversation_id is required")
        if not text:
            raise ValueError("dingtalk: text is required")
        webhook = await self._lookup_webhook(conversation_id)
        if not webhook:
            raise RuntimeError(
                f"dingtalk: no sessionWebhook cached for conversationID={conversation_id} "
                f"(must receive incoming message first)"
            )
        # DingTalk SDK 没有纯 HTTP OpenAPI helper 暴露 — 用 httpx POST sessionWebhook
        import httpx

        body = {
            "msgtype": "text",
            "text": {"content": text},
        }
        if message_id:
            # reply 场景 — 钉钉支持 msg_id 关联(per 文档)
            body["msg_id"] = message_id
        async with httpx.AsyncClient(timeout=10.0) as cli:
            resp = await cli.post(webhook, json=body)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            # 钉钉 reply API 不返回 message_id(DingTalk bot 模型 单向 reply);
            # 返回 callable-side message_id 关联
            return str(data.get("msgid", "") or message_id or "")

    async def update_message(
        self,
        conversation_id: str,
        message_id: str,
        new_text: str,
    ) -> str:
        """DingTalk bot 模型 Stream Mode 没有真 update API(per dingtalk_real.go §196)。

        实际语义:用 cached sessionWebhook 发送 new_text(等同 reply with new content)。
        返回 message_id(保留 = 入参)以维持 caller 一致性。

        :returns: message_id(等同传入 messageID)
        """
        if not conversation_id or not message_id:
            raise ValueError(
                "dingtalk: conversation_id and message_id are required"
            )
        if not new_text:
            raise ValueError("dingtalk: new_text is required")
        webhook = await self._lookup_webhook(conversation_id)
        if not webhook:
            raise RuntimeError(
                f"dingtalk: no sessionWebhook cached for conversationID={conversation_id}"
            )
        import httpx

        body = {
            "msgtype": "text",
            "text": {"content": new_text},
            "msg_id": message_id,
        }
        async with httpx.AsyncClient(timeout=10.0) as cli:
            resp = await cli.post(webhook, json=body)
            resp.raise_for_status()
        return message_id

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
    # DingTalk 内部 helpers
    # ------------------------------------------------------------------

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler

    async def _lookup_webhook(self, conversation_id: str) -> str:
        """读 sessionWebhook 缓存(per dingtalk_real.go §lookupWebhook)。"""
        async with self._webhooks_lock:
            return self._webhooks.get(conversation_id, "")

    async def _stream_run_loop(self) -> None:
        """后台协程:run DingTalkStreamClient.start()(SDK 内部 WS 长连接)。

        SDK 的 start() 内部阻塞 — 用 to_thread 不阻塞 asyncio 循环。
        _stop_event.set() 时退出(per stop())。
        """
        if self._stream_client is None:
            return
        try:
            await asyncio.to_thread(self._stream_client.start)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dingtalk] stream_run_loop ended: %s", exc)

    async def _dispatch_loop(self) -> None:
        """把 events queue 排空到 user handler(reply via PostMessage)。

        收到 IncomingMessage → 调 handler → OutgoingMessage → reply 用 PostMessage。
        conversation_id = incoming.channel_id(钉钉 bot 模型 reply 是 incoming 唯一 API)
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
                    "[dingtalk] handler raised for incoming %s: %s",
                    incoming.platform_msg_id,
                    exc,
                )
                continue
            if outgoing is None:
                continue
            if outgoing.text:
                try:
                    await self.post_message(
                        conversation_id=incoming.channel_id,
                        text=outgoing.text,
                        message_id=incoming.platform_msg_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[dingtalk] post_message failed (conv=%s): %s",
                        incoming.channel_id,
                        exc,
                    )

    def _enqueue_incoming(self, incoming: IncomingMessage) -> None:
        """从 AsyncChatbotHandler callback(SDK 内部线程)推到 asyncio.Queue。"""
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
                "[dingtalk] events queue full, dropping incoming %s",
                incoming.platform_msg_id,
            )


def new_dingtalk_bot(
    app_key: str, app_secret: str, builder: BotBuilder
) -> DingTalkBot:
    """用 app_key + app_secret + builder 创建 DingTalk bot(W6.2 native SDK)。"""
    return DingTalkBot(app_key=app_key, app_secret=app_secret, builder=builder)
