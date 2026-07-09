"""test_slack_e2e.py — SlackBot mock e2e tests (W7.2 D60, 2026-07-09)

3 cases × Slack platform:
  1. test_slack_success         — chat.postMessage 返 200 ok=True,SDK 拿到 ts
  2. test_slack_api_err         — chat.postMessage 返 500,SDK 抛运行时错
  3. test_slack_auth_fail       — auth.test 返 invalid_auth,SDK 抛 ValueError

Mock 策略(per W7.2 拍板):slack-sdk AsyncWebClient 内部用 aiohttp,respx 拦截不到。
改用 unittest.mock.AsyncMock patch AsyncWebClient.chat_postMessage + auth_test。
确保 call_count 严格 == 1,无重试(per 0 门槛 UX)。

参考: wau-channel/internal/adapter/slack/slack_real_test.go。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.slack.bot import SlackBot, new_slack_bot

pytestmark = pytest.mark.integration  # mock SDK 边界,跑 CI 默认环境


def _make_slack_bot() -> SlackBot:
    """构造未启动的 SlackBot 实例(不调 start(),避免走真 WS)"""
    return new_slack_bot(
        bot_token="xoxb-test-token",
        app_token="xapp-test-token",
        builder=new_builder().with_tenant("acme").with_universe("us-prod"),
    )


class _FakeSlackResponse(dict):
    """轻量级 fake Slack AsyncSlackResponse — dict-like + 提供 .data 属性。

    Slack SDK 用 `resp.get("ts", "")` 或 `resp.data["ts"]`,我们两种都支持。
    """

    @property
    def data(self) -> dict:
        return dict(self)


def _attach_mock_client(bot: SlackBot, auth_resp: dict, post_resp: dict) -> AsyncMock:
    """手工注入 mock _client(绕过 start() 的 auth_test 真调)。

    返回 chat_post_message mock 便于断言 call_count / kwargs。
    """
    post_mock = AsyncMock(return_value=_FakeSlackResponse(post_resp))
    auth_mock = AsyncMock(return_value=_FakeSlackResponse(auth_resp))

    client = MagicMock()
    client.auth_test = auth_mock
    client.chat_postMessage = post_mock
    client.chat_update = AsyncMock(
        return_value=_FakeSlackResponse({"ts": "1700000002.000100"})
    )
    bot._client = client
    bot._started = True  # 跳过 start() 守卫
    bot.bot_id = auth_resp.get("bot_id", "B-TEST-001")
    return post_mock


# ---------------------------------------------------------------------------
# Case 1: success — chat.postMessage 返 ok=True,SDK 拿到 ts
# ---------------------------------------------------------------------------

async def test_slack_success() -> None:
    """SlackBot.post_message 走 mock SDK 成功路径(200 ok=True)"""
    bot = _make_slack_bot()
    post_mock = _attach_mock_client(
        bot,
        auth_resp={"bot_id": "B-TEST-001"},
        post_resp={"ts": "1700000001.000100"},
    )

    ts = await bot.post_message(channel_id="C-TEST-CHANNEL", text="hello slack")

    # 1. 返回 ts 与 mock 一致
    assert ts == "1700000001.000100", f"unexpected ts: {ts!r}"
    # 2. chat_postMessage 严格调 1 次
    assert post_mock.call_count == 1, (
        f"chat_postMessage should be called exactly once, got {post_mock.call_count}"
    )
    # 3. 请求 body shape 校验(per Slack API)
    kwargs = post_mock.call_args.kwargs
    assert kwargs["channel"] == "C-TEST-CHANNEL"
    assert kwargs["text"] == "hello slack"


# ---------------------------------------------------------------------------
# Case 2: APIErr — chat.postMessage 抛 SlackApiError(对应 HTTP 500)
# ---------------------------------------------------------------------------

async def test_slack_api_err() -> None:
    """SlackBot.post_message SDK 抛 SlackApiError → SDK 透传为 RuntimeError。

    Slack SDK 行为:chat.postMessage 返 ok=False → 抛 SlackApiError(status_code=500 等)。
    我们的 SDK 透传这个异常,无内部 retry。
    """
    from slack_sdk.errors import SlackApiError

    bot = _make_slack_bot()

    api_err = SlackApiError(
        message="server_error",
        response=MagicMock(status_code=500, data={"ok": False, "error": "server_error"}),
    )
    post_mock = AsyncMock(side_effect=api_err)

    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(bot_id="B-TEST-001"))
    client.chat_postMessage = post_mock
    bot._client = client
    bot._started = True
    bot.bot_id = "B-TEST-001"

    with pytest.raises(SlackApiError) as exc_info:
        await bot.post_message(channel_id="C-TEST", text="boom")

    assert exc_info.value.response.status_code == 500
    # 严格 1 次 — 无 retry
    assert post_mock.call_count == 1, (
        f"should not retry on SlackApiError, got {post_mock.call_count}"
    )


# ---------------------------------------------------------------------------
# Case 3: auth_fail — auth.test 返 invalid_auth → start() 抛 ValueError
# ---------------------------------------------------------------------------

async def test_slack_auth_fail() -> None:
    """SlackBot.start() auth_test 抛 SDK error → 抛 RuntimeError(invalid_auth)。

    模拟 SDK 抛 SlackApiError(401 invalid_auth),start() 应立即失败。
    无 retry(per 0 门槛 UX)。
    """
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web.async_client import AsyncWebClient

    bot = _make_slack_bot()

    auth_err = SlackApiError(
        message="invalid_auth",
        response=MagicMock(status_code=401, data={"ok": False, "error": "invalid_auth"}),
    )
    mock_client = MagicMock()
    mock_client.auth_test = AsyncMock(side_effect=auth_err)

    # Patch AsyncWebClient(token=...) 构造,直接返回我们的 mock_client
    # 这样 start() 第 1 行 `self._client = AsyncWebClient(...)` 拿到我们的 mock
    with patch(
        "wau_sdk.bot.slack.bot.AsyncWebClient",
        return_value=mock_client,
    ):
        with patch("wau_sdk.bot.slack.bot.SocketModeClient") as mock_socket:
            mock_socket.return_value.on_message_listeners = []
            with pytest.raises(RuntimeError) as exc_info:
                await bot.start()
            # 验证底层 auth_test 被调 1 次(无 retry)
            assert mock_client.auth_test.call_count == 1, (
                f"should not retry on auth fail, got {mock_client.auth_test.call_count}"
            )
            # 验证异常携带 invalid_auth 信息
            assert "auth_test failed" in str(exc_info.value)
            # 验证未进一步创建 socket client
            assert mock_socket.call_count == 0
