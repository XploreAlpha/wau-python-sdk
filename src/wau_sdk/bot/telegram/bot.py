"""bot.telegram.bot — TelegramBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/telegram/telegram.go。

Stage 0:只定义 TelegramBot + chain 方法,无实际 Bot API 调用。
Stage 1 M1 子项 7:实装 Telegram Bot API(getUpdates / setWebhook / sendMessage)。
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class TelegramBot(Bot):
    """Telegram Bot stub

    对齐 wau-go-sdk/bot/telegram/telegram.go:14-19 TelegramBot 字段:
        token: str
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

    def __init__(
        self,
        token: str,
        builder: BotBuilder,
    ) -> None:
        self.token: str = token
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

    async def start(self) -> None:
        """启动 bot(stub)。

        Stage 1 实装:Telegram Bot API getUpdates / setWebhook。
        """
        # TODO(stage1-m1): 接入 Telegram Bot API (getUpdates / setWebhook)
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "TelegramBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "TelegramBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "TelegramBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_telegram_bot(token: str, builder: BotBuilder) -> TelegramBot:
    """用 token + builder 创建 Telegram bot(stub)

    对齐 wau-go-sdk/bot/telegram/telegram.go:22 New。
    """
    return TelegramBot(token=token, builder=builder)
