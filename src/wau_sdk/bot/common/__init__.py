"""bot.common — 4 SDK 公共 Bot 基类 / 消息类型 / builder(per D13 拍板:完全统一)

字段名 + 类型必须与 wau-go-sdk/bot/common/{bot,message,options}.go /
wau-typescript-sdk/src/bot/common/ / wau-rust-sdk/src/bot/common/ 100% 一致。
"""

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import Attachment, IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import BotBuilder, new_builder

__all__ = [
    "Attachment",
    "Bot",
    "BotBuilder",
    "IncomingMessage",
    "OutgoingMessage",
    "new_builder",
]
