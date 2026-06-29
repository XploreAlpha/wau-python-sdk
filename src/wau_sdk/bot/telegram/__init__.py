"""bot.telegram — Telegram Bot SDK 集成(stub,Stage 0 脚手架)

Stage 0 脚手架:TelegramBot stub + 编译期接口断言。
Stage 1 M1 子项 7 实装 Telegram Bot API 集成(getUpdates / setWebhook / sendMessage)。
"""

from wau_sdk.bot.telegram.bot import TelegramBot, new_telegram_bot

__all__ = ["TelegramBot", "new_telegram_bot"]
