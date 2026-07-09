"""dingtalk.bot — DingTalkBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/dingtalk/dingtalk.go(per W5 2026-07-13 closure)。

Stage 0:只定义 DingTalkBot + chain 方法,无实际钉钉 Stream SDK 调用。
Stage 1:实装钉钉 Stream API(dingtalk-stream),Stage 1 路径: import dingtalk-stream。
Stage 1 重点:Stream 模式长连接(替代旧版回调),接收事件 / 发送消息 / 卡片回调。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板(Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册(per M10 N3)。

钉钉机器人两种接入方式:
  - 企业内部机器人:app_key + app_secret(本文采用)
  - 群机器人:Webhook + 加签(Stage 1 暂不实现)
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class DingTalkBot(Bot):
    """DingTalk Bot stub

    对齐 wau-go-sdk/bot/dingtalk/dingtalk.go DingTalkBot 字段:
        app_key: str     — 钉钉应用 AppKey
        app_secret: str  — 钉钉应用 AppSecret
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        builder: BotBuilder,
    ) -> None:
        self.app_key: str = app_key
        self.app_secret: str = app_secret
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

    async def start(self) -> None:
        """启动 bot(stub)。

        Stage 1 实装:dingtalk-stream StreamClient + Credential + EventHandler 注册。
        """
        # TODO(stage1): DingTalkStreamClient(app_key, app_secret).start()
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "DingTalkBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "DingTalkBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "DingTalkBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_dingtalk_bot(
    app_key: str, app_secret: str, builder: BotBuilder
) -> DingTalkBot:
    """用 app_key + app_secret + builder 创建 DingTalk bot(stub)

    对齐 wau-go-sdk/bot/dingtalk/dingtalk.go NewDingTalkBot。
    """
    return DingTalkBot(app_key=app_key, app_secret=app_secret, builder=builder)
