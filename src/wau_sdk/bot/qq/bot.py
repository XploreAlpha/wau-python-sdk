"""bot.qq.bot — QQBot fallback httpx + OpenAPI v2 自实现 (W6.2 Stage 1, 2026-07-09)

对齐 wau-go-sdk/bot/qq/qq.go + wau-channel/internal/adapter/qq/qq_real.go。

W6 (2026-07-09) W6.2 实装:
  - 官方 Python SDK 暂缺成熟 lib → fallback httpx + OpenAPI v2 自实现
  - 完整链路:
    鉴权:    POST https://bots.qq.com/app/getAppAccessToken  (app_id + app_secret → access_token)
    WS gateway: GET https://api.sgroup.qq.com/gateway/bot  (拿 WSS URL + sharded 数)
    WSS 收件:    wss://...  →  parse op=0 MESSAGE_CREATE / AT_MESSAGE_CREATE /
                              GROUP_AT_MESSAGE_CREATE / C2C_MESSAGE_CREATE
    发件:    POST https://api.sgroup.qq.com/v2/groups/{group_openid}/messages
            POST https://api.sgroup.qq.com/v2/channels/{channel_id}/messages
            POST https://api.sgroup.qq.com/v2/users/{openid}/messages
    编辑:    PATCH /v2/.../messages/{message_id}

字段对齐 per D13 + D78 + D80:app_id / app_secret / tenant / universe / handler。

为什么 fallback 而非空 stub:per W6.1 拍板 — 5 平台 Stage 1 100% 走 native + fallback;
QQ 官方 SDK 不成熟 → 自实现协议层;W7+ 评估集成 botgo-py(若官方发布)。

用法::

    bot = new_qq_bot(
        app_id="...", app_secret="...",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda m: OutgoingMessage(text=f"echo: {m.text}")),
    )
    asyncio.run(bot.start())
    ...
    asyncio.run(bot.stop())

0 门槛 UX:app_id / app_secret 空立即报错;access_token 缓存 + 401 时刷新(per W7 互联);
WS 断连 → 退避重连。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import httpx
import websockets

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder

logger = logging.getLogger(__name__)

# QQ 开放平台 OpenAPI v2 endpoints(per QQ Bot 官方文档 + botgo SDK)
QQ_API_DOMAIN = "https://api.sgroup.qq.com"
QQ_AUTH_DOMAIN = "https://bots.qq.com"
QQ_SANDBOX_DOMAIN = "https://api.sandbox.qq.com"

QQ_AUTH_URL = f"{QQ_AUTH_DOMAIN}/app/getAppAccessToken"
QQ_GATEWAY_URL = f"{QQ_API_DOMAIN}/gateway/bot"

# WSS gateway 重连参数(per W6.2 0 门槛 UX)
QQ_WS_RECONNECT_BASE_S = 1.0
QQ_WS_RECONNECT_MAX_S = 30.0
QQ_WS_PING_INTERVAL_S = 30.0  # QQ heartbeat: 每 30s 发送 6 op

# channel_type 取值(per qq_real.go channelTypeGuild / Group / Private)
CH_TYPE_GUILD = "2"
CH_TYPE_GROUP = "1"
CH_TYPE_PRIVATE = "0"


class QQBot(Bot):
    """QQ Bot — httpx + OpenAPI v2 fallback 自实现(W6.2 Stage 1)。

    字段(per D13 + D80):
        app_id: str
        app_secret: str
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]

    内部状态:
        _access_token     缓存的 access_token(用 app_id + app_secret 换)
        _token_expires_at access_token 过期 unix 时间戳
        _httpx            AsyncClient(REST 发件 / 编辑 + access_token 鉴权)
        _ws_url           缓存的 WSS URL
        _shards           QQ gateway 推荐 shard 数
        _ws_conn          当前 WebSocket 连接(websockets client)
        _started          start() 防重入
        _stop_event       asyncio.Event
        _events           asyncio.Queue
    """

    bot_id: str

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
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._httpx: Optional[httpx.AsyncClient] = None
        self._ws_url: str = ""
        self._shards: int = 1
        self._ws_conn: Any = None
        self._started: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=64)

        # bot_id 运行时缓存 — 由 gateway 或 POST 响应填充(D80)
        self.bot_id: str = ""

    # ------------------------------------------------------------------
    # Bot interface — 5 public 方法(per D13 + M10 N1)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 QQ Bot(per W6.2:WSS gateway 长连接)。

        步骤:
          1. 校验 app_id / app_secret
          2. 构造 httpx.AsyncClient
          3. 拉 access_token(getAppAccessToken)
          4. 拉 WSS gateway(api.WS / GET /gateway/bot)
          5. 后台协程 dial WSS + run readPump(parse events → events queue)
          6. 启 dispatch loop(events queue → user handler → post)
        """
        if self._started:
            logger.warning("[qq] bot already started (no-op)")
            return

        if not self.app_id or not self.app_secret:
            raise ValueError("qq: app_id and app_secret are required")

        # 1. AsyncClient
        self._httpx = httpx.AsyncClient(timeout=10.0)

        # 2. 拉 access_token(短路:文件 prepopulated 时不要每启动重发)
        try:
            await self._refresh_access_token()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"qq: getAppAccessToken failed: {exc}") from exc

        # 3. 拉 WSS gateway
        try:
            await self._fetch_ws_gateway()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"qq: gateway fetch failed: {exc}") from exc

        self._stop_event.clear()
        self._started = True

        # 4. 启 WS read pump(后台 task;断线退避重连)
        asyncio.create_task(
            self._ws_read_loop(),
            name=f"qq-ws-{self.app_id}",
        )

        # 5. 启 dispatch loop
        asyncio.create_task(
            self._dispatch_loop(),
            name=f"qq-dispatch-{self.app_id}",
        )
        logger.info(
            "[qq] bot started (bot_id=%s, tenant=%s, universe=%s, shards=%d)",
            self.bot_id or "?",
            self.tenant,
            self.universe,
            self._shards,
        )

    async def stop(self) -> None:
        """优雅停止 QQ Bot(per W6.2)。"""
        if not self._started:
            return
        try:
            self._stop_event.set()
            if self._ws_conn is not None:
                try:
                    await self._ws_conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[qq] ws close error: %s", exc)
            if self._httpx is not None:
                await self._httpx.aclose()
                self._httpx = None
            self._access_token = ""
            self._ws_conn = None
            self._started = False
            logger.info("[qq] bot stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[qq] stop error: %s", exc)

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "QQBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "QQBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "QQBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    # ------------------------------------------------------------------
    # QQ-specific public methods(per QQ OpenAPI v2)
    # ------------------------------------------------------------------

    async def post_message(
        self,
        channel_id: str,
        text: str,
        channel_type: str = CH_TYPE_GUILD,
    ) -> str:
        """Send a new message(per QQ OpenAPI v2)。

        channel_type: "2"=guild(channel), "1"=group, "0"=private(c2c)
        :returns: message_id
        """
        if not self._httpx:
            raise RuntimeError("qq: not started (call start() first)")
        if not channel_id:
            raise ValueError("qq: channel_id is required")
        if not text:
            raise ValueError("qq: text is required")

        if channel_type == CH_TYPE_GUILD:
            url = f"{QQ_API_DOMAIN}/v2/channels/{channel_id}/messages"
        elif channel_type == CH_TYPE_GROUP:
            url = f"{QQ_API_DOMAIN}/v2/groups/{channel_id}/messages"
        else:
            url = f"{QQ_API_DOMAIN}/v2/users/{channel_id}/messages"

        body = {
            "content": text,
            "msg_type": 0,  # 0 = text(per QQ OpenAPI v2)
            "msg_id": int(time.time() * 1000),
        }
        await self._ensure_token()
        headers = {
            "Authorization": f"QQBot {self._access_token}",
            "Content-Type": "application/json",
        }
        resp = await self._httpx.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        return str(data.get("id", "") or data.get("msg_id", "") or "")

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        new_text: str,
        channel_type: str = CH_TYPE_GUILD,
    ) -> str:
        """Update an existing message via PATCH /v2/.../messages/{id}。

        :returns: 更新后的 message_id(通常等于传入 message_id)
        """
        if not self._httpx:
            raise RuntimeError("qq: not started (call start() first)")
        if not channel_id or not message_id:
            raise ValueError("qq: channel_id and message_id are required")
        if not new_text:
            raise ValueError("qq: new_text is required")

        if channel_type == CH_TYPE_GUILD:
            base = f"{QQ_API_DOMAIN}/v2/channels/{channel_id}/messages"
        elif channel_type == CH_TYPE_GROUP:
            base = f"{QQ_API_DOMAIN}/v2/groups/{channel_id}/messages"
        else:
            base = f"{QQ_API_DOMAIN}/v2/users/{channel_id}/messages"

        url = f"{base}/{message_id}"
        body = {
            "content": new_text,
            "msg_id": int(time.time() * 1000),
        }
        await self._ensure_token()
        headers = {
            "Authorization": f"QQBot {self._access_token}",
            "Content-Type": "application/json",
        }
        resp = await self._httpx.patch(url, json=body, headers=headers)
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
    # QQ HTTP/WS 内部协议
    # ------------------------------------------------------------------

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler

    async def _refresh_access_token(self) -> None:
        """POST /app/getAppAccessToken 拿 access_token(per QQ Bot 协议)。"""
        if self._httpx is None:
            self._httpx = httpx.AsyncClient(timeout=10.0)
        body = {"appId": self.app_id, "clientSecret": self.app_secret}
        resp = await self._httpx.post(QQ_AUTH_URL, json=body)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token", "") or ""
        expires_in = int(data.get("expires_in", 7200))  # 默认 2 小时
        # 提前 60s 过期更新(per W7 互联)
        self._token_expires_at = time.time() + max(expires_in - 60, 60)
        if not self._access_token:
            raise RuntimeError(f"qq: empty access_token in response: {data}")

    async def _ensure_token(self) -> None:
        """检查 token 即将过期 → 刷新。"""
        if not self._access_token or time.time() >= self._token_expires_at:
            await self._refresh_access_token()

    async def _fetch_ws_gateway(self) -> None:
        """GET /gateway/bot 拿 WSS URL + shards + session limits。"""
        if self._httpx is None:
            self._httpx = httpx.AsyncClient(timeout=10.0)
        await self._ensure_token()
        headers = {"Authorization": f"QQBot {self._access_token}"}
        resp = await self._httpx.get(QQ_GATEWAY_URL, headers=headers)
        if resp.status_code == 401:
            # token 失效 → 刷新重试
            await self._refresh_access_token()
            headers = {"Authorization": f"QQBot {self._access_token}"}
            resp = await self._httpx.get(QQ_GATEWAY_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        self._ws_url = data.get("url", "") or ""
        self._shards = int(data.get("shards", 1))
        if not self._ws_url:
            raise RuntimeError(f"qq: empty WSS URL in response: {data}")

    async def _ws_read_loop(self) -> None:
        """后台协程:dial WSS + 读 WSS 帧 + 解析事件 → events queue。

        断线退避重连:1s,2s,4s,...max 30s。_stop_event.set() 退出。
        """
        backoff = QQ_WS_RECONNECT_BASE_S
        while not self._stop_event.is_set():
            if not self._ws_url:
                # 每个 reconnect 周期刷新一次 gateway(可能 token 过期)
                try:
                    await self._fetch_ws_gateway()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[qq] gateway refresh failed: %s", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, QQ_WS_RECONNECT_MAX_S)
                    continue
            try:
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=QQ_WS_PING_INTERVAL_S,
                    ping_timeout=10.0,
                    close_timeout=5.0,
                ) as ws:
                    self._ws_conn = ws
                    backoff = QQ_WS_RECONNECT_BASE_S
                    logger.info("[qq] WSS connected (url=%s)", self._ws_url)
                    await self._ws_session_loop(ws)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("[qq] WSS read loop error: %s", exc)
                if self._stop_event.is_set():
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, QQ_WS_RECONNECT_MAX_S)
            finally:
                self._ws_conn = None

    async def _ws_session_loop(self, ws: Any) -> None:
        """单 WSS session 处理:Hello → Identify → Ready → Read messages。"""
        # 读 Hello (op=10)— QQ 发 connection limits + heartbeat interval
        hello_raw = await ws.recv()
        hello = json.loads(hello_raw)
        heartbeat_ms = int(hello.get("d", {}).get("heartbeat_interval", 30000))
        logger.debug("[qq] hello hb=%dms", heartbeat_ms)

        # 发 Identify (op=2)— 带 access_token + intents(GuildMessages=1<<9=512)
        identify = {
            "op": 2,
            "d": {
                "token": f"QQBot {self._access_token}",
                "intents": 512 | (1 << 25) | (1 << 18) | (1 << 12),
                "shard": [0, max(self._shards, 1)],
            },
        }
        await ws.send(json.dumps(identify))

        # 启心跳后台 task
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(ws, heartbeat_ms / 1000.0),
            name=f"qq-hb-{self.app_id}",
        )
        try:
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                try:
                    payload = json.loads(raw)
                except (ValueError, TypeError):
                    logger.warning("[qq] skip non-json WSS frame")
                    continue
                incoming = _translate_qq_event(payload)
                if incoming is not None:
                    self._safe_put_nowait(incoming)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self, ws: Any, interval_s: float) -> None:
        """后台心跳(per QQ 协议 op=1):定期发 heartbeat 保 WS。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(interval_s)
                await ws.send(json.dumps({"op": 1, "d": int(time.time())}))
        except asyncio.CancelledError:
            return

    async def _dispatch_loop(self) -> None:
        """把 events queue 排空到 user handler。

        收到 IncomingMessage → 调 handler → OutgoingMessage → post 回原 channel
        (channel_type 由 IncomingMessage payload 维度决定,后续 v1.1.0 + channel_type 元数据)
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
                    "[qq] handler raised for incoming %s: %s",
                    incoming.platform_msg_id,
                    exc,
                )
                continue
            if outgoing is None:
                continue
            if outgoing.text:
                # QQ channel_type 默认 guild;IncomingMessage 暂未透传 channel_type,
                # fallback 留 future-crosspolish(per W7 拍板的 crosspolish matrix)
                try:
                    await self.post_message(
                        channel_id=incoming.channel_id,
                        text=outgoing.text,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[qq] post_message failed (channel=%s): %s",
                        incoming.channel_id,
                        exc,
                    )

    def _safe_put_nowait(self, incoming: IncomingMessage) -> None:
        try:
            self._events.put_nowait(incoming)
        except asyncio.QueueFull:
            logger.warning(
                "[qq] events queue full, dropping incoming %s",
                incoming.platform_msg_id,
            )


def _translate_qq_event(payload: dict) -> Optional[IncomingMessage]:
    """QQ WSS payload → IncomingMessage(per D13 字段对齐)。

    关心的 op=0 事件:
      - t=MESSAGE_CREATE        — channel 消息 (ChannelID = msg.ChannelID)
      - t=AT_MESSAGE_CREATE     — @ 消息
      - t=GROUP_AT_MESSAGE_CREATE — 群 @ (ChannelID = msg.GroupID)
      - t=C2C_MESSAGE_CREATE    — 私聊 (ChannelID = msg.GuildID?;留 "private")

    字段映射(per qq_real.go parseEvent):
        msg.ID     → platform_msg_id
        d.channel_id / d.group_id / d.guild_id → channel_id
        msg.Author.ID → user_id
        msg.Author.Username → username
        msg.Content → text
        msg.Timestamp → timestamp(runtime 临时忽略,跟随 IncomingMessage default)
    """
    if not payload or payload.get("op") != 0:
        return None

    t = payload.get("t", "") or ""
    if t not in (
        "MESSAGE_CREATE",
        "AT_MESSAGE_CREATE",
        "GROUP_AT_MESSAGE_CREATE",
        "C2C_MESSAGE_CREATE",
    ):
        return None

    d = payload.get("d") or {}
    if not d:
        return None

    msg_id = str(d.get("id", "") or "")
    author = d.get("author", {}) or {}
    user_id = str(author.get("id", "") or "")
    username = str(author.get("username", "") or "")
    content = d.get("content", "") or ""

    if t == "GROUP_AT_MESSAGE_CREATE":
        channel_id = str(d.get("group_id", "") or "")
        reply_to = str(d.get("group_openid", "") or "")
    elif t == "C2C_MESSAGE_CREATE":
        channel_id = str(d.get("user_openid", "") or d.get("guild_id", "") or "")
        reply_to = ""
    else:
        # DEFAULT: guild channel
        channel_id = str(d.get("channel_id", "") or d.get("guild_id", "") or "")
        reply_to = ""

    return IncomingMessage(
        platform_msg_id=msg_id,
        channel_id=channel_id,
        user_id=user_id,
        username=username,
        text=content,
        reply_to=reply_to,
    )


def new_qq_bot(
    app_id: str, app_secret: str, builder: BotBuilder
) -> QQBot:
    """用 app_id + app_secret + builder 创建 QQ bot(W6.2 fallback httpx + OpenAPI v2)。"""
    return QQBot(app_id=app_id, app_secret=app_secret, builder=builder)
