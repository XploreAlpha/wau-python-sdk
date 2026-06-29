"""bot.common.bot — Bot 抽象基类(per D13 拍板:4 SDK 方法签名 100% 一致)

抽象方法签名严格对齐 wau-go-sdk/bot/common/bot.go Bot interface:

    async start() -> None
    async stop() -> None
    on_message(handler) -> Bot
    with_tenant(tenant_id) -> Bot
    with_universe(universe) -> Bot

为什么用 ABC 而非 typing.Protocol:
- ABC 强制子类实现抽象方法,运行期就有错
- Protocol 是结构化子类型(只静态检查,mypy 强制)
- 选择 ABC 因为 Bot 子类必须严格符合接口契约(D13 4 SDK 完全统一)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage


# Handler 类型 — Callable[[IncomingMessage], OutgoingMessage]
# 同步签名(per Go SDK func(IncomingMessage) OutgoingMessage)
Handler = "callable[[IncomingMessage], OutgoingMessage]"


class Bot(ABC):
    """通用 Bot 抽象基类(per D13:4 SDK 必须实现同样的方法签名)

    4 SDK 必须实现的方法签名 100% 一致:
      - async start() -> None
      - async stop() -> None
      - on_message(handler) -> Bot
      - with_tenant(tenant_id) -> Bot
      - with_universe(universe) -> Bot
    """

    @abstractmethod
    async def start(self) -> None:
        """启动 bot(长连接 / webhook server)"""

    @abstractmethod
    async def stop(self) -> None:
        """优雅停止"""

    @abstractmethod
    def on_message(self, handler):  # type: ignore[no-untyped-def]
        """注册消息处理 handler,返回 Bot 支持链式调用

        Args:
            handler: Callable[[IncomingMessage], OutgoingMessage]
        """
        raise NotImplementedError

    @abstractmethod
    def with_tenant(self, tenant_id: str) -> "Bot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        raise NotImplementedError

    @abstractmethod
    def with_universe(self, universe: str) -> "Bot":
        """设置 Universe 标签(W-6),返回 Bot 支持链式调用"""
        raise NotImplementedError
