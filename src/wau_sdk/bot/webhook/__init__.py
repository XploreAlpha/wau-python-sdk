"""bot.webhook — 通用 Webhook Bot SDK 集成(stub,Stage 0 脚手架)

Stage 0 脚手架:WebhookBot stub + 编译期接口断言。
Stage 1 M1 子项 9 实装 HTTPS POST 端点 + 签名验证 + 消息归一化。
"""

from wau_sdk.bot.webhook.bot import WebhookBot, new_webhook_bot

__all__ = ["WebhookBot", "new_webhook_bot"]
