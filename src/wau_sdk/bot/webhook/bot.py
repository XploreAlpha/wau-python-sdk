"""bot.webhook.bot — WebhookBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/webhook/webhook.go。

Stage 0:只定义 WebhookBot + chain 方法,无实际 HTTP server。
Stage 1 M1 子项 9:实装 HTTPS POST 端点 + 签名验证 + 消息归一化。
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class WebhookBot(Bot):
    """Webhook Bot stub

    对齐 wau-go-sdk/bot/webhook/webhook.go:14-19 WebhookBot 字段:
        addr: str          — HTTP listen address, e.g. ":8080"
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

    def __init__(
        self,
        addr: str,
        builder: BotBuilder,
    ) -> None:
        self.addr: str = addr
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

    async def start(self) -> None:
        """启动 webhook server(stub)。

        Stage 1 实装:HTTP server + 签名验证 + 消息归一化。
        """
        # TODO(stage1-m1): http.Server + 签名验证 + 消息归一化
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "WebhookBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "WebhookBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "WebhookBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_webhook_bot(addr: str, builder: BotBuilder) -> WebhookBot:
    """用 addr + builder 创建 Webhook bot(stub)

    对齐 wau-go-sdk/bot/webhook/webhook.go:22 New。
    """
    return WebhookBot(addr=addr, builder=builder)
