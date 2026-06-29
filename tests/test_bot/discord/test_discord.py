"""bot.discord.test_bot — DiscordBot stub 单测(Stage 0)

6 case 镜像 wau-go-sdk/bot/discord/discord_test.go:
  1. New(token, builder) 返回 DiscordBot
  2. New 自动从 builder 拷贝 tenant / universe / handler
  3. async start / stop 不报错
  4. on_message chain 后 handler 覆盖
  5. with_tenant / with_universe chain
  6. 编译期 isinstance DiscordBot 是 Bot 子类
"""

from __future__ import annotations

import pytest

from wau_sdk.bot.common.bot import Bot
from wau_sdk.bot.common.message import IncomingMessage, OutgoingMessage
from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.discord import DiscordBot, new_discord_bot


def test_new_returns_discord_bot() -> None:
    """new_discord_bot 返回 DiscordBot 实例"""
    bot = new_discord_bot("discord-bot-token", new_builder())
    assert bot is not None
    assert isinstance(bot, DiscordBot)


def test_new_copies_builder_fields() -> None:
    """builder 字段全部透传到 DiscordBot"""
    bot = new_discord_bot(
        "discord-bot-token",
        new_builder()
        .with_tenant("acme")
        .on_message(lambda msg: OutgoingMessage(text="ack")),
    )
    assert bot.token == "discord-bot-token"
    assert bot.tenant == "acme"
    assert bot.handler is not None


@pytest.mark.asyncio
async def test_start_stop_no_error() -> None:
    """Stage 0 stub:start / stop 不报错"""
    bot = new_discord_bot("t", new_builder())
    await bot.start()
    await bot.stop()


def test_on_message_chain_overrides_handler() -> None:
    """on_message 链式调用覆盖 builder.handler"""
    called = {"flag": False}

    def handler(_msg: IncomingMessage) -> OutgoingMessage:
        called["flag"] = True
        return OutgoingMessage(text="ok")

    bot = new_discord_bot("t", new_builder()).on_message(handler)
    assert bot.handler is not None
    bot.handler(IncomingMessage(text="hi"))
    assert called["flag"] is True


def test_with_tenant_and_universe_chain() -> None:
    """with_tenant / with_universe 链式调用返回 Bot 类型"""
    bot = new_discord_bot("t", new_builder())
    result: Bot = bot.with_tenant("t1").with_universe("cn-prod")
    assert result is bot
    assert bot.tenant == "t1"
    assert bot.universe == "cn-prod"


def test_discord_bot_is_bot() -> None:
    """DiscordBot 是 Bot 子类(对应 Go var _ botcommon.Bot = ...)"""
    bot = new_discord_bot("t", new_builder())
    assert isinstance(bot, Bot)
