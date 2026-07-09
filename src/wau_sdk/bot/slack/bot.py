"""bot.slack.bot — SlackBot native SDK integration (W6.2 Stage 1, 2026-07-09)

对齐 wau-go-sdk/bot/slack/slack.go + wau-channel/internal/adapter/slack/slack_real.go。

W6 (2026-07-09) W6.2 Stage 1 实装:
  - Native SDK: slack-sdk>=3.27(AsyncWebClient + SocketModeClient)
  - Start       → Socket Mode WS 长连接(slack_sdk.socket_mode.aiohttp.SocketModeClient)
  - Stop        → cancel SocketModeClient + 关 WebClient
  - PostMessage → AsyncWebClient.chat_postMessage(channel, text)
  - UpdateMessage→ AsyncWebClient.chat_update(channel, ts, text)
  - SubmitToCore 走 wau_sdk.tasks.AsyncTasksService.submit()(可选, 未配 SDK 不报错)

公共 Bot interface 沿用 M10 N1 + D13:Start / Stop / OnMessage / WithTenant / WithUniverse。

字段对齐 per D13 + D78 + D80:bot_token / app_token / tenant / universe / handler。

Slack Socket Mode 说明(per slack-sdk doc):
  - SocketModeClient 拉 wss://wss-primary.slack.com + 自动管理 WS lifecycle
  - EventType: events_api / interactive / slash_commands
  - 我们只关心 events_api(message event)+ UserID ≠ self.botID 过滤(自己发的不重入)
  - translate message event → wau_sdk.bot.common.message.IncomingMessage

用法::

    bot = new_slack_bot(
        bot_token="xoxb-...", app_token="xapp-...",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda m: OutgoingMessage(text=f"echo: {m.text}")),
    )
    asyncio.run(bot.start())     # 长连接
    ...
    asyncio.run(bot.stop())      # 优雅停止

0 门槛 UX:bot_token / app_token 空立即报错;运行期 SocketModeClient
连接失败 → start() 抛错;事件 channel 满 → drop + log(不阻塞 SDK)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder

logger = logging.getLogger(__name__)

# SDK 导入(per W6.1 dep 追加)。try/except 留 SlackBot 可单独 import 而不强制
# slack-sdk(测试可 mock 缺失),与 wau-go-sdk pattern 一致。
try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest

    _SLACK_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - 容错(测试 / 离线场景)
    AsyncWebClient = None  # type: ignore[assignment,misc]
    SocketModeClient = None  # type: ignore[assignment,misc]
    SocketModeRequest = None  # type: ignore[assignment,misc]
    _SLACK_SDK_AVAILABLE = False


class SlackBot(Bot):
    """Slack Bot — native slack-sdk async 集成(W6.2 Stage 1)。

    字段(per D13 + D80):
        bot_token: str      — Bot User OAuth Token (xoxb-...)
        app_token: str      — App-Level Token for Socket Mode (xapp-...)
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]

    内部状态:
        _client          AsyncWebClient 实例(per W6.2 — slack-sdk WebClient)
        _socket_client   SocketModeClient WS 长连接
        _started         start() 防重入
        _stop_event      asyncio.Event(stop signal)
        _events          asyncio.Queue 用于 receive 端 → handler 桥接
    """

    # BotID 缓存(AuthTest 拿,运行时首次 start 后填)
    bot_id: str

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        builder: BotBuilder,
    ) -> None:
        self.bot_token: str = bot_token
        self.app_token: str = app_token
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

        # W6.2 实装字段
        self._client: Optional[AsyncWebClient] = None
        self._socket_client: Optional[SocketModeClient] = None
        self._started: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=128)

        # W6.2 ops runtime state
        self.bot_id: str = ""
        self._listen_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Bot interface — 5 public 方法(per D13 + M10 N1)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 Slack Bot(per W6.2 Socket Mode WS 长连接)。

        步骤:
          1. 校验 token 必填
          2. 构造 AsyncWebClient + SocketModeClient
          3. 调 auth_test 拿 botID(per D80 透传)
          4. 注册 on_message listener(过滤 self.botID,翻译成 IncomingMessage → events queue)
          5. 后台启 listen_task 跑 SocketModeClient.connect() + handler dispatch
        """
        if self._started:
            logger.warning("[slack] bot already started (no-op)")
            return

        if not _SLACK_SDK_AVAILABLE:
            raise RuntimeError(
                "slack-sdk not installed (W6.1 dep slack-sdk>=3.27 缺失, "
                "pip install slack-sdk)"
            )

        if not self.bot_token:
            raise ValueError("slack: bot_token is required")
        if not self.app_token:
            raise ValueError(
                "slack: app_token is required (Socket Mode requires xapp-...)"
            )

        # 1. 构造 AsyncWebClient(REST API client:chat.postMessage / chat.update / auth.test)
        self._client = AsyncWebClient(token=self.bot_token)

        # 2. auth_test 拿 botID(D80 透传 + 自发自过滤)
        try:
            auth_resp = await self._client.auth_test()
            self.bot_id = auth_resp.get("bot_id", "") or ""
        except Exception as exc:  # noqa: BLE001 — 0 门槛 UX 包错
            raise RuntimeError(f"slack: auth_test failed: {exc}") from exc

        # 3. 构造 SocketModeClient(on_message listener 用 lambda 桥 events queue)
        self._socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self._client,
        )

        def _on_message(
            client: SocketModeClient,
            req: SocketModeRequest,
        ) -> None:
            """SocketModeClient message listener(SDK 内部回调,同步签名)。

            过滤 self.botID(避免自发自收)→ 翻译 events_api 消息 → 推 events queue。
            """
            try:
                if req.type != "events_api":
                    return
                envelope = req.payload or {}
                event = envelope.get("event", {}) or {}
                if event.get("type") != "message":
                    return
                # 自发自过滤(per D80)
                if self.bot_id and event.get("user") == self.bot_id:
                    return
                # 翻译(同步 → queue.put_nowait + run_coroutine_threadsafe)
                incoming = _translate_slack_event(envelope, event)
                if incoming is None:
                    return
                self._enqueue_incoming(incoming)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[slack] on_message handler failed: %s", exc)

        self._socket_client.on_message_listeners.append(_on_message)

        # 4. 启 listener + dispatch loop
        self._stop_event.clear()
        self._started = True
        self._listen_task = asyncio.create_task(
            self._listen_loop(),
            name=f"slack-listen-{self.bot_id or 'unknown'}",
        )

        # 5. 启 dispatch loop(把 events queue → user handler → 可选 update)
        asyncio.create_task(
            self._dispatch_loop(),
            name=f"slack-dispatch-{self.bot_id or 'unknown'}",
        )
        logger.info(
            "[slack] bot started (bot_id=%s, tenant=%s, universe=%s)",
            self.bot_id,
            self.tenant,
            self.universe,
        )

    async def stop(self) -> None:
        """优雅停止 Slack Bot(per W6.2)。

        步骤:
          1. _stop_event.set()(让 listener / dispatch loop 退出)
          2. SocketModeClient.disconnect()(close WS)
          3. aclose WebClient aiohttp session
          4. cancel _listen_task(等 done,带超时)
        """
        if not self._started:
            return
        try:
            self._stop_event.set()
            if self._socket_client is not None:
                # SDK 内部 aiohttp.ClientSession — close 即可
                try:
                    await self._socket_client.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[slack] socket_client.close error: %s", exc)
            if self._listen_task is not None:
                self._listen_task.cancel()
                try:
                    await asyncio.wait_for(self._listen_task, timeout=3.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            self._started = False
            logger.info("[slack] bot stopped (bot_id=%s)", self.bot_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[slack] stop error: %s", exc)

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "SlackBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "SlackBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "SlackBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    # ------------------------------------------------------------------
    # Slack-specific public methods(per Slack Bot 协议)
    # ------------------------------------------------------------------

    async def post_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: str = "",
    ) -> str:
        """Send a new message to channel via chat.postMessage(per Slack Bot API)。

        :returns: Slack ts(timestamp string)用作 update/edit 的 handle
        """
        if not self._client:
            raise RuntimeError("slack: not started (call start() first)")
        if not channel_id:
            raise ValueError("slack: channel_id is required")
        if not text:
            raise ValueError("slack: text is required")
        kwargs: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        resp = await self._client.chat_postMessage(**kwargs)
        # AsyncSlackResponse 兼容 dict-like + .data
        ts = resp.get("ts", "") or ""
        if not ts and hasattr(resp, "data"):
            ts = (resp.data or {}).get("ts", "") or ""
        return ts

    async def update_message(
        self,
        channel_id: str,
        ts: str,
        new_text: str,
    ) -> str:
        """Update an existing message via chat.update。

        :returns: Slack ts(updated timestamp)
        """
        if not self._client:
            raise RuntimeError("slack: not started (call start() first)")
        if not channel_id or not ts:
            raise ValueError("slack: channel_id and ts are required")
        if not new_text:
            raise ValueError("slack: new_text is required")
        resp = await self._client.chat_update(
            channel=channel_id,
            ts=ts,
            text=new_text,
        )
        new_ts = resp.get("ts", "") or ""
        if not new_ts and hasattr(resp, "data"):
            new_ts = (resp.data or {}).get("ts", "") or ""
        return new_ts

    async def submit_to_core(
        self,
        prompt: str,
        timeout_ms: int = 30000,
    ) -> dict:
        """通过 wau_sdk.tasks.submit 把 prompt 提交到 wau-core-kernel(per W6.2)。

        :returns: SubmitResponse dict(task_id / agent_id / status 等)
        """
        # lazy import 防循环引用
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

    async def _listen_loop(self) -> None:
        """后台协程:run SocketModeClient.connect()。

        SocketModeClient.connect() 内部处理 WS lifecycle + reconnect + listeners。
        _stop_event.set() 时退出(per stop())。
        """
        if self._socket_client is None:
            return
        try:
            # connect() 是 SDK 的阻塞入口(内部 aiohttp WS);用 to_thread 跑不阻塞 asyncio 循环
            await asyncio.to_thread(self._socket_client.connect, self._stop_event)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[slack] listen_loop ended: %s", exc)

    async def _dispatch_loop(self) -> None:
        """把 events queue 排空到 user handler。

        收到 IncomingMessage → 调 self._handler(IncomingMessage) → 拿 OutgoingMessage
        → 用 OutgoingMessage.text post 回 原 channel(or reply_to 维度交给 future-crosspolish)。
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
                    "[slack] handler raised for incoming %s: %s",
                    incoming.platform_msg_id,
                    exc,
                )
                continue
            if outgoing is None:
                continue
            if outgoing.text:
                try:
                    await self.post_message(
                        channel_id=incoming.channel_id,
                        text=outgoing.text,
                        thread_ts=incoming.reply_to or "",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[slack] post_message failed (channel=%s): %s",
                        incoming.channel_id,
                        exc,
                    )

    def _enqueue_incoming(self, incoming: IncomingMessage) -> None:
        """从同步 listener 把 IncomingMessage 推到 asyncio.Queue。

        queue 满了丢 + log(per W6.2 0 门槛 UX)。run_coroutine_threadsafe 保兼容。
        """
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
                "[slack] events queue full, dropping incoming %s",
                incoming.platform_msg_id,
            )


def _translate_slack_event(envelope: dict, event: dict) -> Optional[IncomingMessage]:
    """Slack events_api payload → IncomingMessage(per D13 字段对齐)。

    关键字段映射:
        ts / channel / user / text / thread_ts → IncomingMessage 8 字段
    """
    if not event:
        return None
    ts = event.get("ts", "") or envelope.get("event_id", "")
    return IncomingMessage(
        platform_msg_id=ts,
        channel_id=event.get("channel", "") or "",
        user_id=event.get("user", "") or "",
        username=event.get("username", "") or "",
        text=event.get("text", "") or "",
        reply_to=event.get("thread_ts", "") or "",
    )


# 编译期接口断言(per D13 pattern)
def new_slack_bot(
    bot_token: str, app_token: str, builder: BotBuilder
) -> SlackBot:
    """用 bot_token + app_token + builder 创建 Slack bot(W6.2 native SDK)。"""
    return SlackBot(bot_token=bot_token, app_token=app_token, builder=builder)
