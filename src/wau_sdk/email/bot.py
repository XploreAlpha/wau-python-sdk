"""email.bot — EmailBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/email/email.go(per W5 2026-07-13 closure)。

Stage 0:只定义 EmailBot + chain 方法,无实际 IMAP/SMTP 调用。
Stage 1:实装 IMAP IDLE 收件 + SMTP 发件,Stage 1 路径: import imapclient + smtplib(stdlib)。
Stage 1 重点:IMAP IDLE 推送实现实时收件(IMAP4 IDLE 命令,rfc2177),SMTP 走 TLS 发件。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板(Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册(per M10 N3)。

Email Bot 与其他 IM Bot 的关键差异:
  - 无 WebSocket / 无 Webhook:基于 IMAP IDLE 长连接 + SMTP 主动发件
  - 鉴权:用户名 + 密码(或 OAuth2,Stage 1 暂用密码)
  - 消息 thread:用 Message-ID / In-Reply-To 标识
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class EmailBot(Bot):
    """Email Bot stub

    对齐 wau-go-sdk/bot/email/email.go EmailBot 字段:
        imap_host: str   — IMAP 服务器地址, e.g. imap.gmail.com
        smtp_host: str   — SMTP 服务器地址, e.g. smtp.gmail.com
        username: str    — 邮箱地址
        password: str    — 邮箱密码 / 应用专用密码
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

    def __init__(
        self,
        imap_host: str,
        smtp_host: str,
        username: str,
        password: str,
        builder: BotBuilder,
    ) -> None:
        self.imap_host: str = imap_host
        self.smtp_host: str = smtp_host
        self.username: str = username
        self.password: str = password
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

    async def start(self) -> None:
        """启动 bot(stub)。

        Stage 1 实装:IMAP IDLE 长连接(收件) + SMTP TLS 发件。
        """
        # TODO(stage1): imapclient.IMAPClient + smtplib.SMTP_SSL
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
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
        """已注册的 handler(供测试用)"""
        return self._handler


def new_email_bot(
    imap_host: str,
    smtp_host: str,
    username: str,
    password: str,
    builder: BotBuilder,
) -> EmailBot:
    """用 imap_host + smtp_host + username + password + builder 创建 Email bot(stub)

    对齐 wau-go-sdk/bot/email/email.go NewEmailBot。
    """
    return EmailBot(
        imap_host=imap_host,
        smtp_host=smtp_host,
        username=username,
        password=password,
        builder=builder,
    )
