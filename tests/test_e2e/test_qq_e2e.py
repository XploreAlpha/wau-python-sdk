"""test_qq_e2e.py — QQBot mock e2e tests (W7.2 D60, 2026-07-09)

3 cases × QQ (OpenAPI v2 + httpx fallback) platform:
  1. test_qq_success       — channels/{id}/messages 返 200,SDK 拿到 message_id
  2. test_qq_api_err       — channels/{id}/messages 返 500,SDK 抛 httpx.HTTPStatusError
  3. test_qq_auth_fail     — getAppAccessToken 返 401 invalid_client,start() 抛 RuntimeError

Mock 策略(per W7.2 拍板):QQBot 内部用 httpx.AsyncClient,respx 完美拦截。
- channels: https://api.sgroup.qq.com/v2/channels/{channel_id}/messages
- auth:    https://bots.qq.com/app/getAppAccessToken

为简化,跳过 start() 的 WSS gateway 拉取,直接注入 httpx + access_token(经
prepopulated token 路径),只测 post_message 的 HTTP 边界。

参考: wau-channel/internal/adapter/qq/qq_real_test.go。
"""
from __future__ import annotations

import httpx
import pytest
import respx

from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.qq.bot import (
    CH_TYPE_GUILD,
    QQ_API_DOMAIN,
    QQ_AUTH_URL,
    QQBot,
    new_qq_bot,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_qq_bot() -> QQBot:
    return new_qq_bot(
        app_id="qq_test_appid",
        app_secret="qq_test_secret",
        builder=new_builder().with_tenant("acme").with_universe("us-prod"),
    )


def _inject_qq_state(bot: QQBot, access_token: str = "qq_test_token") -> None:
    """注入预热的 httpx client + access_token,跳过 start() 的鉴权/WSS 拉取。

    仅供 e2e 测 post_message / 错误路径使用,start() 路径由 test_qq_auth_fail 覆盖。
    """
    bot._httpx = httpx.AsyncClient(timeout=10.0)
    bot._access_token = access_token
    bot._token_expires_at = 9_999_999_999.0  # 永不超时
    bot._ws_url = ""  # 不启 WS
    bot._started = True


# ---------------------------------------------------------------------------
# Case 1: success — channels/{id}/messages 返 200 → SDK 拿到 message_id
# ---------------------------------------------------------------------------

async def test_qq_success() -> None:
    """QQBot.post_message 走 mock httpx,respx 拦截 channels endpoint。"""
    bot = _make_qq_bot()
    _inject_qq_bot_state = _inject_qq_state(bot)
    channel_id = "qq_channel_001"

    with respx.mock(assert_all_called=False) as mock:
        post_route = mock.post(
            f"{QQ_API_DOMAIN}/v2/channels/{channel_id}/messages"
        ).mock(return_value=httpx.Response(200, json={"id": "qq_msg_001"}))

        msg_id = await bot.post_message(
            channel_id=channel_id, text="hello qq"
        )

    assert msg_id == "qq_msg_001", f"unexpected msg_id: {msg_id!r}"
    # 严格 1 次 — 无 retry
    assert post_route.call_count == 1, (
        f"channels POST should be called exactly once, got {post_route.call_count}"
    )
    # 请求 body shape(per QQ OpenAPI v2)
    request = post_route.calls[0].request
    body = request.read()
    import json
    payload = json.loads(body)
    assert payload["content"] == "hello qq"
    assert payload["msg_type"] == 0  # text


# ---------------------------------------------------------------------------
# Case 2: APIErr — channels/{id}/messages 返 500 → SDK 抛 HTTPStatusError
# ---------------------------------------------------------------------------

async def test_qq_api_err() -> None:
    """QQBot.post_message 返 500 → httpx.Response.raise_for_status() 抛 HTTPStatusError。"""
    bot = _make_qq_bot()
    _inject_qq_state(bot)
    channel_id = "qq_channel_err"

    with respx.mock(assert_all_called=False) as mock:
        post_route = mock.post(
            f"{QQ_API_DOMAIN}/v2/channels/{channel_id}/messages"
        ).mock(
            return_value=httpx.Response(
                500, json={"retcode": 500, "message": "internal error"}
            )
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await bot.post_message(channel_id=channel_id, text="will fail")

    assert exc_info.value.response.status_code == 500
    # 严格 1 次 — 无 retry(QQ SDK 没内部 retry,401 时只是刷新 token)
    assert post_route.call_count == 1, (
        f"should not retry on 500, got {post_route.call_count}"
    )


# ---------------------------------------------------------------------------
# Case 3: auth_fail — getAppAccessToken 返 401 → start() 抛 RuntimeError
# ---------------------------------------------------------------------------

async def test_qq_auth_fail() -> None:
    """QQBot.start() getAppAccessToken 返 401 → SDK 包成 RuntimeError。

    per QQ OpenAPI v2,401 invalid_client 意味着 appid/secret 错。
    """
    bot = _make_qq_bot()

    with respx.mock(assert_all_called=False) as mock:
        auth_route = mock.post(QQ_AUTH_URL).mock(
            return_value=httpx.Response(
                401,
                json={
                    "retcode": 401,
                    "message": "invalid_client",
                },
            )
        )

        with pytest.raises(RuntimeError) as exc_info:
            await bot.start()
        # 验证底层 getAppAccessToken 被调 1 次
        assert auth_route.call_count == 1, (
            f"getAppAccessToken should be called exactly once, got {auth_route.call_count}"
        )
        # 验证异常携带 auth fail 信息
        assert "getAppAccessToken failed" in str(exc_info.value)
        # bot 未启动
        assert bot._started is False
