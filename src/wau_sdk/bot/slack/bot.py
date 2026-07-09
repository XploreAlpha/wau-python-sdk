"""bot.slack.bot — SlackBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/slack/slack.go(per W5 2026-07-13 closure,commit 87b566c)。

Stage 0:只定义 SlackBot + chain 方法,无实际 Slack SDK 调用。
Stage 1:实装 Socket Mode(github.com/slack-go/slack + slack-go/socketmode),
Stage 1 路径: import slack-sdk(WebClient + SocketModeClient)。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板(Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册(per M10 N3)。
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class SlackBot(Bot):
    """Slack Bot stub

    对齐 wau-go-sdk/bot/slack/slack.go:28-38 SlackBot 字段:
        bot_token: str  — Bot User OAuth Token (xoxb-...)
        app_token: str  — App-Level Token for Socket Mode (xapp-...)
        tenant: str
        universe: str
        handler: Callable[[IncomingMessage], OutgoingMessage]
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        builder: BotBuilder,
    ) -> None:
        self.bot_token: str = bot_token
        self.app_token: str = app_token
        self.tenant: str = builder.tenant_id()
        self.universe: str = builder.universe()
        self._handler: Optional[Callable[[IncomingMessage], OutgoingMessage]] = (
            builder.handler()
        )

    async def start(self) -> None:
        """启动 bot(stub)。

        Stage 1 实装:Slack Socket Mode (WS 长连接,接收事件)。
        """
        # TODO(stage1): WebClient(token=...) + SocketModeClient(app_token=...)
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "SlackBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "SlackBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "SlackBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_slack_bot(
    bot_token: str, app_token: str, builder: BotBuilder
) -> SlackBot:
    """用 bot_token + app_token + builder 创建 Slack bot(stub)

    对齐 wau-go-sdk/bot/slack/slack.go:48 NewSlackBot。
    """
    return SlackBot(bot_token=bot_token, app_token=app_token, builder=builder)
