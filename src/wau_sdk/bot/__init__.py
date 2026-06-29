"""WAU Python SDK — Bot 子包(per v0.9.0 Stage 0 / D13 拍板)

子包结构(镜像 wau-go-sdk/bot/):

    wau_sdk.bot.common    — 4 SDK 公共接口(IncomingMessage / OutgoingMessage /
                            Attachment / Bot 基类 / BotBuilder)
    wau_sdk.bot.telegram  — Telegram Bot SDK 集成(stub,Stage 0)
    wau_sdk.bot.discord   — Discord Bot SDK 集成(stub,Stage 0)
    wau_sdk.bot.webhook   — 通用 Webhook Bot SDK 集成(stub,Stage 0)

Stage 0:只搭骨架 + Bot 基类 + 3 个 stub Bot 实现。
Stage 1 M1 子项 7-9 实装 Telegram Bot API / Discord Bot Gateway / HTTP Webhook 接入。

字段名 + 类型必须与 wau-go-sdk / wau-typescript-sdk / wau-rust-sdk 100% 一致
(per D13:4 SDK Bot interface 完全统一)。
"""

from wau_sdk.bot.common import (
    Attachment,
    Bot,
    BotBuilder,
    IncomingMessage,
    OutgoingMessage,
    new_builder,
)
from wau_sdk.bot.telegram import TelegramBot, new_telegram_bot
from wau_sdk.bot.discord import DiscordBot, new_discord_bot
from wau_sdk.bot.webhook import WebhookBot, new_webhook_bot

__all__ = [
    # common
    "Attachment",
    "Bot",
    "BotBuilder",
    "IncomingMessage",
    "OutgoingMessage",
    "new_builder",
    # telegram
    "TelegramBot",
    "new_telegram_bot",
    # discord
    "DiscordBot",
    "new_discord_bot",
    # webhook
    "WebhookBot",
    "new_webhook_bot",
]
