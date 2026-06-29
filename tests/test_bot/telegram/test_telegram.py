"""bot.telegram.test_bot — TelegramBot stub 单测(Stage 0)

6 case 镜像 wau-go-sdk/bot/telegram/telegram_test.go:
  1. New(token, builder) 返回 TelegramBot(非 None)
  2. New 自动从 builder 拷贝 tenant / universe / handler
  3. async start / stop 不报错(stub)
  4. on_message chain 后 handler 覆盖
  5. with_tenant / with_universe chain 返回 Bot
  6. 编译期 isinstance TelegramBot 是 Bot 子类
"""

from __future__ import annotations

import asyncio

import pytest

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.telegram import TelegramBot, new_telegram_bot


# ---------- 1. New + 字段透传 ----------

def test_new_returns_telegram_bot() -> None:
    """new_telegram_bot 返回 TelegramBot 实例"""
    bot = new_telegram_bot("1234:test-token", new_builder())
    assert bot is not None
    assert isinstance(bot, TelegramBot)


def test_new_copies_builder_fields() -> None:
    """builder 字段全部透传到 TelegramBot"""
    bot = new_telegram_bot(
        "1234:test-token",
        new_builder()
        .with_tenant("acme")
        .with_universe("us-prod")
        .on_message(lambda msg: OutgoingMessage(text=f"echo: {msg.text}")),
    )
    assert bot.token == "1234:test-token"
    assert bot.tenant == "acme"
    assert bot.universe == "us-prod"
    assert bot.handler is not None


# ---------- 2. async start / stop ----------

@pytest.mark.asyncio
async def test_start_stop_no_error() -> None:
    """Stage 0 stub:start / stop 不报错"""
    bot = new_telegram_bot("test-token", new_builder())
    await bot.start()
    await bot.stop()


# ---------- 3. on_message chain ----------

def test_on_message_chain_overrides_handler() -> None:
    """on_message 链式调用覆盖 builder.handler"""
    called = {"flag": False}

    def handler(_msg: IncomingMessage) -> OutgoingMessage:
        called["flag"] = True
        return OutgoingMessage(text="ok")

    bot = new_telegram_bot("t", new_builder()).on_message(handler)
    assert bot.handler is not None
    bot.handler(IncomingMessage(text="hi"))
    assert called["flag"] is True


# ---------- 4. with_tenant / with_universe chain ----------

def test_with_tenant_and_universe_chain() -> None:
    """with_tenant / with_universe 链式调用返回 Bot 类型"""
    bot = new_telegram_bot("t", new_builder())
    # chain 返回 Bot 类型(基类),支持后续链式
    result: Bot = bot.with_tenant("t1").with_universe("cn-prod")
    assert result is bot
    assert bot.tenant == "t1"
    assert bot.universe == "cn-prod"


# ---------- 5. 编译期 isinstance 检查 ----------

def test_telegram_bot_is_bot() -> None:
    """TelegramBot 是 Bot 子类(对应 Go var _ botcommon.Bot = ...)"""
    bot = new_telegram_bot("t", new_builder())
    assert isinstance(bot, Bot)
