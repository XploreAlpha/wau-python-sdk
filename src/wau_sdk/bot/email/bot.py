"""bot.email.bot — EmailBot stub (Stage 0 脚手架)

对齐 wau-go-sdk/bot/email/email.go (per W5 2026-07-13 closure)。
W6 (2026-07-09) W5 缺口补全:Python SDK 补 email 子包。

Stage 0:只定义 EmailBot + chain 方法,无实际 IMAP/SMTP 调用。
Stage 1:实装 imapclient (异步 IMAP IDLE) + stdlib smtplib (SMTP 发送),
        Stage 1 路径在 W6.2 落地。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板 (Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册 (per M10 N3)。

Email Bot 平台说明 (与 IM/Slack 等不同):
  - 接收消息:IMAP IDLE 模式长连接到 IMAP server (imap.gmail.com:993)
  - 发送消息:SMTP (smtp.gmail.com:587 + STARTTLS) — 走 stdlib smtplib
  - 鉴权:username + password (或 OAuth2 XOAUTH2)
  - 邮件解析:email.message.EmailMessage (stdlib)
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class EmailBot(Bot):
    """Email Bot stub

    对齐 wau-go-sdk/bot/email/email.go EmailBot 字段:
        imap_host: str   — IMAP server hostname (e.g. imap.gmail.com)
        imap_port: int   — IMAP server port (993 for SSL)
        smtp_host: str   — SMTP server hostname (e.g. smtp.gmail.com)
        smtp_port: int   — SMTP server port (587 for STARTTLS)
        username: str    — 邮箱地址
        password: str    — 邮箱密码或 app password
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

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

    async def start(self) -> None:
        """启动 bot (stub)。

        Stage 1 实装:imapclient.IMAPClient(host, port, ssl=True) + idle()
        长连接 + select_folder('INBOX') + 事件分发到 _handler。
        """
        # TODO(stage1): imapclient.IMAPClient + idle() + select_folder('INBOX')
        return None

    async def stop(self) -> None:
        """优雅停止 (stub)"""
        return None

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

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler (供测试用)"""
        return self._handler


def new_email_bot(
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    builder: BotBuilder,
) -> EmailBot:
    """用 IMAP/SMTP 配置 + builder 创建 Email bot (stub)

    对齐 wau-go-sdk/bot/email/email.go NewEmailBot。
    """
    return EmailBot(
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        builder=builder,
    )