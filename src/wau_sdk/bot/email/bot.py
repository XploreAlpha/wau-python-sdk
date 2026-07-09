"""bot.email.bot — EmailBot native SDK integration (W6.2 Stage 1, 2026-07-09)

对齐 wau-go-sdk/bot/email/email.go + wau-channel/internal/adapter/email/email_real.go。

W6 (2026-07-09) W6.2 实装:
  - Native SDK: imapclient>=3.0(IMAP IDLE 主动推送)
              + stdlib smtplib(SMTP 发送 — 不引入额外 dep)
  - Start       → IMAPClient(host, port, ssl=True).login() + select_folder('INBOX')
                  + IDLE 主循环 fetch 增量 → 翻译 events → queue
  - Stop        → stop IDLE + Logout + close
  - PostMessage → smtplib.SMTP(host, port) + starttls + login + sendmail
  - UpdateMessage → "Update" = Send message with In-Reply-To + References headers
                    (per email_real.go §sendMessage / buildRFC2822 邮件 thread 语义)

字段对齐 per D13 + D78 + D80:
    imap_host / imap_port / smtp_host / smtp_port / username / password /
    tenant / universe / handler

IMAP IDLE 语义说明(per email_real.go §13-16):
  - IMAP 协议不允许 IDLE 期间 Fetch;必须先停 IDLE → Fetch → 重启 IDLE
  - lastUID 记录已处理的邮件 UID 上界,增量 fetch > lastUID
  - 邮件 thread 单向性:Message-ID → ChannelID(per email_real.go §9 + handleEvent)

用法::

    bot = new_email_bot(
        imap_host="imap.gmail.com", imap_port=993,
        smtp_host="smtp.gmail.com", smtp_port=587,
        username="bot@gmail.com", password="app-password",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda m: OutgoingMessage(text=f"Re: {m.text}")),
    )
    asyncio.run(bot.start())
    ...
    asyncio.run(bot.stop())

0 门槛 UX:username / password 空立即报错;IMAP IDLE 断连 → 重连带退避;
events channel 满 → drop + log。
"""
from __future__ import annotations

import asyncio
import email
import email.message
import logging
import smtplib
import ssl
from typing import Any, Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder

logger = logging.getLogger(__name__)

# SDK 导入(per W6.1 dep 追加)
try:
    from imapclient import IMAPClient

    _IMAPCLIENT_AVAILABLE = True
except ImportError:  # pragma: no cover
    IMAPClient = None  # type: ignore[assignment,misc]
    _IMAPCLIENT_AVAILABLE = False

# IMAP IDLE reconnection parameters(per W6.2 0 门槛 UX)
IMAP_RECONNECT_BASE_S = 1.0
IMAP_RECONNECT_MAX_S = 30.0

# IDLE poll interval(imapclient 的 idle_done/idle_check 模式)
IMAP_IDLE_POLL_S = 1.0


class EmailBot(Bot):
    """Email Bot — imapclient + smtplib native 集成(W6.2 Stage 1)。

    字段(per D13 + D80):
        imap_host: str   — IMAP server hostname (e.g. imap.gmail.com)
        imap_port: int   — IMAP server port (993 for SSL)
        smtp_host: str   — SMTP server hostname (e.g. smtp.gmail.com)
        smtp_port: int   — SMTP server port (587 for STARTTLS)
        username: str    — 邮箱地址
        password: str    — 邮箱密码或 app password
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]

    内部状态:
        _imap_client   imapclient.IMAPClient 实例
        _last_uid      已处理邮件 UID 上界(增量 fetch 用)
        _started       start() 防重入
        _stop_event    asyncio.Event
        _events        asyncio.Queue
    """

    bot_id: str

    def __init__(
        self,
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        builder: BotBuilder,
    ) -> None:
        self.imap_host: str = imap_host
        self.imap_port: int = imap_port
        self.smtp_host: str = smtp_host
        self.smtp_port: int = smtp_port
        self.username: str = username
        self.password: str = password
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

        # W6.2 实装字段
        self._imap_client: Optional[IMAPClient] = None
        self._last_uid: int = 0
        self._started: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=64)

        # bot_id 透传(per D80)— 用 username 当 bot_id 简化
        self.bot_id: str = username

    # ------------------------------------------------------------------
    # Bot interface — 5 public 方法(per D13 + M10 N1)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 Email Bot(per W6.2:IMAP IDLE 主动推送)。

        步骤:
          1. 校验 imap_host / username / password
          2. 构造 IMAPClient + login + select_folder('INBOX')
          3. 拿 mailbox 当前 status,记 lastUID(避免重复推 existing mails)
          4. 后台协程跑 IDLE 主循环:停 IDLE → fetch > lastUID → 重启 IDLE
          5. 启 dispatch loop(把 events queue → user handler → SMTP send)
        """
        if self._started:
            logger.warning("[email] bot already started (no-op)")
            return

        if not _IMAPCLIENT_AVAILABLE:
            raise RuntimeError(
                "imapclient not installed (W6.1 dep imapclient>=3.0 缺失, "
                "pip install imapclient)"
            )

        if not self.imap_host or not self.username or not self.password:
            raise ValueError(
                "email: imap_host, username, password are required"
            )

        self._stop_event.clear()
        self._started = True

        # 1. 启 IDLE 主循环(IMAP 协议是 sync,所以包 to_thread)
        asyncio.create_task(
            self._idle_run_loop(),
            name=f"email-imap-{self.username}",
        )

        # 2. 启 dispatch loop
        asyncio.create_task(
            self._dispatch_loop(),
            name=f"email-dispatch-{self.username}",
        )
        logger.info(
            "[email] bot started (imap=%s:%d, smtp=%s:%d, tenant=%s, universe=%s)",
            self.imap_host,
            self.imap_port,
            self.smtp_host,
            self.smtp_port,
            self.tenant,
            self.universe,
        )

    async def stop(self) -> None:
        """优雅停止 Email Bot(per W6.2)。"""
        if not self._started:
            return
        try:
            self._stop_event.set()
            if self._imap_client is not None:
                try:
                    # IDLE 退避 → Logout 顺序
                    await asyncio.to_thread(
                        self._logout_and_close_imap,
                        self._imap_client,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[email] imap logout error: %s", exc)
                self._imap_client = None
            self._started = False
            logger.info("[email] bot stopped (username=%s)", self.username)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[email] stop error: %s", exc)

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "EmailBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "EmailBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "EmailBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    # ------------------------------------------------------------------
    # Email-specific public methods(per SMTP 协议)
    # ------------------------------------------------------------------

    async def post_message(
        self,
        to_address: str,
        text: str,
        subject: str = "(no subject)",
        message_id: str = "",
    ) -> str:
        """Send a new email via SMTP(per RFC 2822 + email_real.go §buildRFC2822)。

        reply 场景(message_id 非空)→ 加 In-Reply-To + References header(邮件 thread)。

        :returns: 拼接的 Message-ID(供 reply 用)
        """
        if not to_address:
            raise ValueError("email: to_address is required")
        if not text:
            raise ValueError("email: text is required")
        try:
            await asyncio.to_thread(
                self._smtp_send,
                to_address,
                subject,
                text,
                message_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"email: smtp send failed: {exc}") from exc
        new_msg_id = f"<{self.username}-{to_address}-{asyncio.get_event_loop().time()}>"
        return new_msg_id

    async def update_message(
        self,
        to_address: str,
        message_id: str,
        new_text: str,
    ) -> str:
        """邮件 thread 单向性:UpdateMessage = Send with In-Reply-To + References。

        per email_real.go §287 buildRFC2822 reply 路径 — 加 "Re: " 主题前缀
        + In-Reply-To + References header,使收件人客户端把回信归到原 thread。

        :returns: message_id(caller 一致性,等同入参)
        """
        if not to_address or not message_id:
            raise ValueError("email: to_address and message_id are required")
        if not new_text:
            raise ValueError("email: new_text is required")
        try:
            await asyncio.to_thread(
                self._smtp_send_with_reply,
                to_address,
                message_id,
                new_text,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"email: smtp reply failed: {exc}") from exc
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
    # Email 内部 IMAP / SMTP helpers
    # ------------------------------------------------------------------

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler

    def _smtp_send(
        self,
        to_address: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
    ) -> None:
        """构造 RFC 2822 邮件 + 发 SMTP(sync helper,to_thread 调用)。

        Reply 路径 (in_reply_to 非空) 加 In-Reply-To + References header + "Re: " 主题前缀。
        """
        msg = email.message.EmailMessage()
        msg["From"] = self.username
        msg["To"] = to_address
        if in_reply_to:
            subj = subject
            if not subj.lower().startswith("re:"):
                subj = f"Re: {subj}"
            msg["Subject"] = subj
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        else:
            msg["Subject"] = subject
        msg.set_content(body)

        ctx = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as srv:
            srv.starttls(context=ctx)
            srv.login(self.username, self.password)
            srv.send_message(msg)

    def _smtp_send_with_reply(
        self,
        to_address: str,
        in_reply_to: str,
        new_text: str,
    ) -> None:
        """reply 路径专用 helper(per email_real.go §287 reply 路径)。

        Subject 默认 "(no subject)";加 In-Reply-To + References。
        """
        self._smtp_send(
            to_address=to_address,
            subject="(no subject)",
            body=new_text,
            in_reply_to=in_reply_to,
        )

    def _logout_and_close_imap(self, client: IMAPClient) -> None:
        """同步 logout + close(IMAP 4 logout 顺序)。"""
        try:
            client.idle_done()
        except Exception:  # noqa: BLE001
            pass
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass

    def _connect_imap(self) -> IMAPClient:
        """构造 IMAPClient + login + select_folder('INBOX')(sync helper)。"""
        ssl_ctx = ssl.create_default_context()
        cli = IMAPClient(
            self.imap_host,
            port=self.imap_port,
            ssl=True,
            ssl_context=ssl_ctx,
            timeout=10.0,
        )
        cli.login(self.username, self.password)
        cli.select_folder("INBOX")
        return cli

    async def _idle_run_loop(self) -> None:
        """后台协程:connect IMAP → IDLE 循环 → 增量 fetch → 翻译 events。

        断连退避重连:1s,2s,4s,...max 30s。_stop_event.set() 退出。
        """
        backoff = IMAP_RECONNECT_BASE_S
        while not self._stop_event.is_set():
            try:
                cli = await asyncio.to_thread(self._connect_imap)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("[email] IMAP connect failed: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, IMAP_RECONNECT_MAX_S)
                continue
            self._imap_client = cli
            backoff = IMAP_RECONNECT_BASE_S
            logger.info(
                "[email] IMAP connected (%s:%d, mailbox=INBOX)",
                self.imap_host,
                self.imap_port,
            )

            try:
                await asyncio.to_thread(self._idle_pump, cli)
            except asyncio.CancelledError:
                # 退出前 Logout
                try:
                    await asyncio.to_thread(
                        self._logout_and_close_imap, cli
                    )
                except Exception:  # noqa: BLE001
                    pass
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("[email] IDLE pump error: %s", exc)
            finally:
                self._imap_client = None

            if self._stop_event.is_set():
                return

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, IMAP_RECONNECT_MAX_S)

    def _idle_pump(self, cli: IMAPClient) -> None:
        """IDLE 主循环:scan [lastUID+1, ...] → 翻译 → events queue。

        imapclient 的 idle() 也有 (sync 阻塞) — 为简化主循环,我们轮询 search()
        拿到 latest UID 后增量 fetch。这样比 IDLE poll 简单,适合大多数 SMTP/IMAP。
        """
        while not self._stop_event.is_set():
            try:
                # 找所有 unseen + > lastUID 的邮件 UID
                # imapclient.search() 接受 criteria;常见:["UID", "N:*"] + ["UNSEEN"]
                message_ids = cli.search(["UID", f"{self._last_uid + 1}:*"])
                if not message_ids:
                    # 进入 IDLE 等待新邮件(per imapclient IDLE 模式)
                    cli.idle()
                    try:
                        # idle_check 阻塞直到新邮件或 timeout
                        cli.idle_check(timeout=IMAP_IDLE_POLL_S)
                    finally:
                        cli.idle_done()
                    continue
                # 增量 fetch
                fetch_data = cli.fetch(
                    message_ids,
                    ["UID", "ENVELOPE", "BODY[TEXT]"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[email] search/fetch failed: %s", exc)
                return  # 让外层重连

            for msg_id, data in fetch_data.items():
                envelope = data.get(b"ENVELOPE") if isinstance(data, dict) else None
                if envelope is None:
                    continue
                incoming = _translate_imap_envelope(msg_id, envelope, data)
                if incoming is None:
                    continue
                if msg_id > self._last_uid:
                    self._last_uid = msg_id
                # 推 events queue
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(self._safe_put_nowait, incoming)
                else:
                    self._safe_put_nowait(incoming)

    async def _dispatch_loop(self) -> None:
        """把 events queue 排空到 user handler。

        收到 IncomingMessage(channel_id = From email, text = Subject + Body?) →
        handler → OutgoingMessage → 构造 SMTP send → to=From email(per 邮件 thread 协议)
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
                    "[email] handler raised for incoming %s: %s",
                    incoming.platform_msg_id,
                    exc,
                )
                continue
            if outgoing is None:
                continue
            if outgoing.text:
                # 邮件 thread:reply 到原 From(per email_real.go §287)
                # channel_id 用 From 邮箱地址(暂用透传,future-crosspolish 拍 To 维度)
                try:
                    await self.update_message(
                        to_address=incoming.channel_id or incoming.username,
                        message_id=incoming.platform_msg_id,
                        new_text=outgoing.text,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[email] reply failed (to=%s): %s",
                        incoming.channel_id,
                        exc,
                    )

    def _safe_put_nowait(self, incoming: IncomingMessage) -> None:
        try:
            self._events.put_nowait(incoming)
        except asyncio.QueueFull:
            logger.warning(
                "[email] events queue full, dropping incoming %s",
                incoming.platform_msg_id,
            )


def _translate_imap_envelope(
    msg_id: int, envelope: Any, fetch_data: Any
) -> Optional[IncomingMessage]:
    """imapclient fetch envelope → IncomingMessage(per D13 字段对齐)。

    字段映射(per email_real.go §parseIMAPMessage):
        env.message_id     → platform_msg_id
        env.from[0]        → channel_id (mailbox@host)
        env.from[0].name   → username
        env.subject        → text(per handleEvent Subject → Text 约定)
        env.date           → timestamp
        BODY[TEXT]         → text(若 Subject 为空)
    """
    try:
        # envelope object(imapclient 返回 imap4.parsed 后的对象)— 安全读 attribute
        msgid = getattr(envelope, "message_id", None) or b""
        if isinstance(msgid, bytes):
            msgid = msgid.decode("utf-8", errors="replace")
        if not msgid:
            msgid = f"<imap-uid-{msg_id}>"

        from_list = getattr(envelope, "from_", None) or []
        if not from_list:
            return None
        from_addr = from_list[0]
        mailbox = getattr(from_addr, "mailbox", None) or b""
        host = getattr(from_addr, "host", None) or b""
        if isinstance(mailbox, bytes):
            mailbox = mailbox.decode("utf-8", errors="replace")
        if isinstance(host, bytes):
            host = host.decode("utf-8", errors="replace")
        from_email = (
            f"{mailbox}@{host}" if mailbox and host else (mailbox or host or "")
        )

        username = getattr(from_addr, "name", None) or ""
        if isinstance(username, bytes):
            username = username.decode("utf-8", errors="replace")

        subject = getattr(envelope, "subject", None) or ""
        if isinstance(subject, bytes):
            subject = subject.decode("utf-8", errors="replace")

        # 如果 subject 空,fallback 到 BODY[TEXT] (per handleEvent fallback)
        text = subject
        body_text = (
            fetch_data.get(b"BODY[TEXT]") if isinstance(fetch_data, dict) else None
        )
        if not text and body_text:
            try:
                text = body_text.decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001
                text = ""

        return IncomingMessage(
            platform_msg_id=msgid,
            channel_id=from_email,
            user_id=from_email,
            username=username,
            text=text,
        )
    except Exception:  # noqa: BLE001
        return None


def new_email_bot(
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    builder: BotBuilder,
) -> EmailBot:
    """用 IMAP/SMTP 配置 + builder 创建 Email bot(W6.2 native SDK)。"""
    return EmailBot(
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        builder=builder,
    )
