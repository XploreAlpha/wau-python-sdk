"""bot.qq.bot — QQBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/qq/qq.go(per W5 2026-07-13 closure)。

Stage 0:只定义 QQBot + chain 方法,无实际 QQ Bot SDK 调用。
Stage 1:实装 QQ 机器人 SDK(基于 QQ 开放平台 WebSocket 网关),
Stage 1 路径: import qq-bot-sdk(qqbot.Client + 事件回调)。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板(Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册(per M10 N3)。

QQ Bot 平台说明:
  - QQ 群机器人:app_id + app_secret 鉴权(沙箱/正式环境 endpoint 不同)
  - 接收消息:WebSocket 网关 wss://api.sgroup.qq.com/connect
  - 发送消息:POST /v2/groups/{group_openid}/messages
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class QQBot(Bot):
    """QQ Bot stub

    对齐 wau-go-sdk/bot/qq/qq.go QQBot 字段:
        app_id: str      — QQ 机器人 App ID
        app_secret: str  — QQ 机器人 App Secret(client secret)
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

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

    async def start(self) -> None:
        """启动 bot(stub)。

        Stage 1 实装:QQ 机器人 WebSocket 网关 + access_token 刷新 + 事件分发。
        """
        # TODO(stage1): qqbot.Client(app_id, app_secret) + WebSocket 网关
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

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

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_qq_bot(
    app_id: str, app_secret: str, builder: BotBuilder
) -> QQBot:
    """用 app_id + app_secret + builder 创建 QQ bot(stub)

    对齐 wau-go-sdk/bot/qq/qq.go NewQQBot。
    """
    return QQBot(app_id=app_id, app_secret=app_secret, builder=builder)
