"""bot.feishu.bot — FeishuBot stub(Stage 0 脚手架)

对齐 wau-go-sdk/bot/feishu/feishu.go(per W5 2026-07-13 closure)。

Stage 0:只定义 FeishuBot + chain 方法,无实际飞书 SDK 调用。
Stage 1:实装飞书 Open API(lark-oapi),Stage 1 路径: import lark-oapi(LARK_APP_ID/LARK_APP_SECRET)。
Stage 1 重点:消息接收走 WebSocket(ws://open.feishu.cn/open-apis/socket/v1/connect)
            + 事件回调 v2 协议。

字段对齐 per D13 拍板:与 wau-channel/adapter + 4 SDK bot/common/ 100% 一致。
公共 Bot interface 沿用 M10 N1 拍板(Start/Stop/OnMessage/WithTenant/WithUniverse)。
仍走 wau-edge POST /v1/bots/{bot_id}/messages 注册(per M10 N3)。
"""

from __future__ import annotations

from typing import Callable, Optional

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder


class FeishuBot(Bot):
    """Feishu (Lark) Bot stub

    对齐 wau-go-sdk/bot/feishu/feishu.go FeishuBot 字段:
        app_id: str      — 飞书应用 App ID (cli_...)
        app_secret: str  — 飞书应用 App Secret
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

        Stage 1 实装:飞书 Open API WebSocket 长连接 + 事件回调 v2。
        """
        # TODO(stage1): lark.Client(app_id, app_secret) + lark.ws.Client
        return None

    async def stop(self) -> None:
        """优雅停止(stub)"""
        return None

    def on_message(
        self, handler: Callable[[IncomingMessage], OutgoingMessage]
    ) -> "FeishuBot":
        """注册消息处理 handler,返回 Bot 支持链式调用"""
        self._handler = handler
        return self

    def with_tenant(self, tenant_id: str) -> "FeishuBot":
        """设置 tenant_id,返回 Bot 支持链式调用"""
        self.tenant = tenant_id
        return self

    def with_universe(self, universe: str) -> "FeishuBot":
        """设置 Universe 标签,返回 Bot 支持链式调用"""
        self.universe = universe
        return self

    @property
    def handler(self) -> Optional[Callable[[IncomingMessage], OutgoingMessage]]:
        """已注册的 handler(供测试用)"""
        return self._handler


def new_feishu_bot(
    app_id: str, app_secret: str, builder: BotBuilder
) -> FeishuBot:
    """用 app_id + app_secret + builder 创建 Feishu bot(stub)

    对齐 wau-go-sdk/bot/feishu/feishu.go NewFeishuBot。
    """
    return FeishuBot(app_id=app_id, app_secret=app_secret, builder=builder)
