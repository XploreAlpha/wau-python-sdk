"""bot.webhook.test_bot — WebhookBot stub 单测(Stage 0)

5 case 镜像 wau-go-sdk/bot/webhook/webhook_test.go:
  1. New(addr, builder) 返回 WebhookBot
  2. async start / stop 不报错
  3. builder handler 全部字段透传
  4. handler 可直接 invoke(模拟收到 webhook 后调用)
  5. 编译期 isinstance WebhookBot 是 Bot 子类
"""

from __future__ import annotations

import pytest

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.webhook import WebhookBot, new_webhook_bot


def test_new_returns_webhook_bot() -> None:
    """new_webhook_bot 返回 WebhookBot 实例"""
    bot = new_webhook_bot(":8080", new_builder().with_tenant("acme"))
    assert bot is not None
    assert isinstance(bot, WebhookBot)
    assert bot.addr == ":8080"
    assert bot.tenant == "acme"


@pytest.mark.asyncio
async def test_start_stop_no_error() -> None:
    """Stage 0 stub:start / stop 不报错"""
    bot = new_webhook_bot(":0", new_builder())
    await bot.start()
    await bot.stop()


def test_builder_fields_copied() -> None:
    """builder 字段全部透传到 WebhookBot"""
    bot = new_webhook_bot(
        ":9000",
        new_builder()
        .with_tenant("acme")
        .with_universe("cn-prod")
        .on_message(lambda _msg: OutgoingMessage(text="ok")),
    )
    assert bot.addr == ":9000"
    assert bot.tenant == "acme"
    assert bot.universe == "cn-prod"
    assert bot.handler is not None


def test_handler_direct_invocation() -> None:
    """handler 可直接 invoke(模拟 webhook 触发 handler)"""
    called = {"flag": False}

    def handler(_msg: IncomingMessage) -> OutgoingMessage:
        called["flag"] = True
        return OutgoingMessage(text="ok")

    bot = new_webhook_bot(
        ":0",
        new_builder().on_message(handler),
    )
    assert bot.handler is not None
    bot.handler(IncomingMessage(text="hi"))
    assert called["flag"] is True


def test_webhook_bot_is_bot() -> None:
    """WebhookBot 是 Bot 子类(对应 Go var _ botcommon.Bot = ...)"""
    bot = new_webhook_bot(":0", new_builder())
    assert isinstance(bot, Bot)
