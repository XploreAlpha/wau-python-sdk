"""bot.common.options — BotBuilder(per feedback-dev-style 偏好 builder 模式)

用法::

    from wau_sdk.bot import new_builder, new_telegram_bot

    bot = new_telegram_bot(
        token="1234:test-token",
        builder=new_builder()
            .with_tenant("acme")
            .with_universe("us-prod")
            .on_message(lambda msg: OutgoingMessage(text=f"echo: {msg.text}")),
    )

对齐 wau-go-sdk/bot/common/options.go BotBuilder。
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Handler  # type: ignore[attr-defined]
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage


class BotBuilder:
    """BotBuilder — 通用 builder(per feedback-dev-style)"""

    def __init__(self) -> None:
        self._tenant_id: str = ""
        self._universe: str = ""
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = None

    def with_tenant(self, tenant_id: str) -> "BotBuilder":
        """设置 tenant_id"""
        self._tenant_id = tenant_id
        return self

    def with_universe(self, universe: str) -> "BotBuilder":
        """设置 Universe 标签"""
        self._universe = universe
        return self

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "BotBuilder":
        """注册消息处理 handler"""
        self._handler = handler
        return self

    # ---------- getters(供具体 adapter 读取)----------

    def tenant_id(self) -> str:
        """返回已设置的 tenant_id"""
        return self._tenant_id

    def universe(self) -> str:
        """返回已设置的 universe"""
        return self._universe

    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """返回已注册的 handler"""
        return self._handler


def new_builder() -> BotBuilder:
    """创建 BotBuilder(等价于 Go 的 botcommon.NewBuilder())

    Stage 0:返回 BotBuilder,Stage 1 雏形期具体 adapter 用 BotBuilder 构建具体 Bot。
    """
    return BotBuilder()
