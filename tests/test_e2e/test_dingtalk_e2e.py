"""test_dingtalk_e2e.py — DingTalkBot mock e2e tests (W7.2 D60, 2026-07-09)

3 cases × DingTalk (Stream Mode bot 模型) platform:
  1. test_dingtalk_success      — sessionWebhook 返 200,SDK 拿到 msgid
  2. test_dingtalk_api_err      — sessionWebhook 返 500,SDK 抛 HTTPStatusError
  3. test_dingtalk_auth_fail    — app_key/app_secret 空 → start() 抛 ValueError

Mock 策略(per W7.2 拍板):DingTalkBot.post_message 内部用 httpx.AsyncClient 临时构造
POST 到 cached sessionWebhook URL,respx 拦截。

前置:DingTalk bot 模型 Stream Mode 必须先收到 incoming event 缓存 sessionWebhook
才能 reply。我们直接 inject webhook 进 _webhooks dict(等价于"已收到 1 条 incoming")。

参考: wau-channel/internal/adapter/dingtalk/dingtalk_real_test.go。
"""
from __future__ import annotations

import httpx
import pytest
import respx

from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.dingtalk.bot import DingTalkBot, new_dingtalk_bot

pytestmark = pytest.mark.integration

# 固定测试 webhook URL,respx 拦截它
TEST_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=mock_test_token"
TEST_CONVERSATION_ID = "conv_dingtalk_001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dingtalk_bot() -> DingTalkBot:
    return new_dingtalk_bot(
        app_key="ding_test_appkey",
        app_secret="ding_test_appsecret",
        builder=new_builder().with_tenant("acme").with_universe("us-prod"),
    )


def _inject_webhook(bot: DingTalkBot, conv_id: str = TEST_CONVERSATION_ID) -> None:
    """注入 cached sessionWebhook(等价于"已收到 1 条 incoming")+ 启动态。

    不调 start() 跳过 WS 长连接 + AsyncChatbotHandler 注册。
    """
    bot._webhooks[conv_id] = TEST_WEBHOOK_URL
    bot._started = True


# ---------------------------------------------------------------------------
# Case 1: success — sessionWebhook 返 200 → SDK 拿到 msgid
# ---------------------------------------------------------------------------

async def test_dingtalk_success() -> None:
    """DingTalkBot.post_message 走 mock httpx,respx 拦截 sessionWebhook POST。"""
    bot = _make_dingtalk_bot()
    _inject_webhook(bot)

    with respx.mock(assert_all_called=False) as mock:
        post_route = mock.post(TEST_WEBHOOK_URL).mock(
            return_value=httpx.Response(
                200, json={"errcode": 0, "errmsg": "ok", "msgid": "dt_msg_001"}
            )
        )

        msg_id = await bot.post_message(
            conversation_id=TEST_CONVERSATION_ID, text="hello dingtalk"
        )

    assert msg_id == "dt_msg_001", f"unexpected msgid: {msg_id!r}"
    # 严格 1 次 — 无 retry
    assert post_route.call_count == 1, (
        f"webhook POST should be called exactly once, got {post_route.call_count}"
    )
    # 请求 body shape(per 钉钉 bot 模型)
    request = post_route.calls[0].request
    import json
    payload = json.loads(request.read())
    assert payload["msgtype"] == "text"
    assert payload["text"]["content"] == "hello dingtalk"


# ---------------------------------------------------------------------------
# Case 2: APIErr — sessionWebhook 返 500 → SDK 抛 HTTPStatusError
# ---------------------------------------------------------------------------

async def test_dingtalk_api_err() -> None:
    """DingTalkBot.post_message 返 500 → httpx.raise_for_status() 抛 HTTPStatusError。"""
    bot = _make_dingtalk_bot()
    _inject_webhook(bot)

    with respx.mock(assert_all_called=False) as mock:
        post_route = mock.post(TEST_WEBHOOK_URL).mock(
            return_value=httpx.Response(
                500, json={"errcode": 500, "errmsg": "internal error"}
            )
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await bot.post_message(
                conversation_id=TEST_CONVERSATION_ID, text="will fail"
            )

    assert exc_info.value.response.status_code == 500
    # 严格 1 次 — 无 retry
    assert post_route.call_count == 1, (
        f"should not retry on 500, got {post_route.call_count}"
    )


# ---------------------------------------------------------------------------
# Case 3: auth_fail — app_key/app_secret 空 → start() 抛 ValueError
# ---------------------------------------------------------------------------

async def test_dingtalk_auth_fail() -> None:
    """DingTalkBot.start() app_key/app_secret 空 → 抛 ValueError(required)。

    0 门槛 UX:app_key / app_secret 任一空立即报错(per bot.py §155)。
    """
    bot = new_dingtalk_bot(
        app_key="",
        app_secret="",  # 双空,触发守门
        builder=new_builder(),
    )

    with pytest.raises(ValueError) as exc_info:
        await bot.start()

    assert "required" in str(exc_info.value).lower()
    # bot 未启动
    assert bot._started is False
