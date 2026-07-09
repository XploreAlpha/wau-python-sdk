"""test_feishu_e2e.py — FeishuBot mock e2e tests (W7.2 D60, 2026-07-09)

3 cases × Feishu (Lark) platform:
  1. test_feishu_success      — acreate 返 success=True,SDK 拿到 message_id
  2. test_feishu_api_err      — acreate 返 success=False code≠0,SDK 抛 RuntimeError
  3. test_feishu_auth_fail    — app_id/app_secret 空 → start() 抛 ValueError

Mock 策略(per W7.2 拍板):lark-oapi 内部用 httpx 但封装复杂,改用 AsyncMock patch
`lark.Client.im.v1.message.acreate` 直接拦截 SDK response。

环境 quirk:lark-oapi 当前版本 `lark_oapi.event.EventDispatcher` 不再导出,导致
FeishuBot 模块顶层 try-import 整段失败(CreateMessageRequestBody 也变成 None)。
我们用 _bootstrap_lark_sdk() 在每个 test 里把缺失符号注入 wau_sdk.bot.feishu.bot
模块名空间,等价于"假装 SDK 已装好"(不修改任何源码文件)。

参考: wau-channel/internal/adapter/feishu/feishu_real_test.go。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wau_sdk.bot.common.options import new_builder
import wau_sdk.bot.feishu.bot as feishu_bot_mod
from wau_sdk.bot.feishu.bot import FeishuBot, new_feishu_bot

pytestmark = pytest.mark.integration


@dataclass
class _FakeLarkData:
    message_id: str = ""


@dataclass
class _FakeLarkResp:
    """轻量 fake lark CreateMessageResponse — 提供 success()/code/msg/data 属性"""

    ok: bool
    code: int = 0
    msg: str = ""
    message_id: str = ""

    def success(self) -> bool:
        return self.ok

    @property
    def data(self) -> _FakeLarkData:
        return _FakeLarkData(message_id=self.message_id)


# ---------------------------------------------------------------------------
# SDK bootstrap — 把 lark-oapi 的 builder class 注入到 bot 模块名空间
# ---------------------------------------------------------------------------


class _FakeBuilder:
    """Fake lark CreateMessageRequestBody.builder() — 支持链式调用 .receive_id().msg_type().content().build()"""

    def __init__(self) -> None:
        self.receive_id_v = ""
        self.msg_type_v = ""
        self.content_v = ""

    def receive_id(self, v: str) -> "_FakeBuilder":
        self.receive_id_v = v
        return self

    def msg_type(self, v: str) -> "_FakeBuilder":
        self.msg_type_v = v
        return self

    def content(self, v: str) -> "_FakeBuilder":
        self.content_v = v
        return self

    def build(self) -> "_FakeBuilder":
        return self


class _FakeRequestBuilder:
    def __init__(self) -> None:
        self.receive_id_type_v = ""
        self.request_body_v: Any = None

    def receive_id_type(self, v: str) -> "_FakeRequestBuilder":
        self.receive_id_type_v = v
        return self

    def request_body(self, body: Any) -> "_FakeRequestBuilder":
        self.request_body_v = body
        return self

    def build(self) -> "_FakeRequestBuilder":
        return self


class _FakeRequest:
    """Fake lark CreateMessageRequest — 提供 builder() 类方法"""

    @classmethod
    def builder(cls) -> _FakeRequestBuilder:
        return _FakeRequestBuilder()


class _FakeRequestBody:
    """Fake lark CreateMessageRequestBody — 提供 builder() 类方法"""

    @classmethod
    def builder(cls) -> _FakeBuilder:
        return _FakeBuilder()


def _bootstrap_lark_sdk() -> None:
    """把 fake builder class 注入 feishu bot 模块,等价于 import 成功。

    必须在每个 test 入口调,确保 _FEISHU_SDK_AVAILABLE=True 且 builder class 可用。
    """
    feishu_bot_mod._FEISHU_SDK_AVAILABLE = True
    feishu_bot_mod.CreateMessageRequestBody = _FakeRequestBody  # type: ignore[attr-defined]
    feishu_bot_mod.CreateMessageRequest = _FakeRequest  # type: ignore[attr-defined]


def _make_feishu_bot() -> FeishuBot:
    return new_feishu_bot(
        app_id="cli_test_id",
        app_secret="cli_test_secret",
        builder=new_builder().with_tenant("acme").with_universe("us-prod"),
    )


def _attach_mock_lark_client(bot: FeishuBot, acreate_resp: Any) -> AsyncMock:
    """注入 mock _lark_client;返回 acreate mock 供断言。

    bot._lark_client.im.v1.message.acreate 是 SDK 实际调用的位置。
    """
    acreate_mock = AsyncMock(return_value=acreate_resp)

    message_v1 = MagicMock()
    message_v1.acreate = acreate_mock
    message_v1.apatch = AsyncMock(
        return_value=_FakeLarkResp(ok=True, message_id="om_test_001")
    )

    im_v1 = MagicMock()
    im_v1.message = message_v1

    lark_client = MagicMock()
    lark_client.im = im_v1
    lark_client.im.v1 = im_v1

    bot._lark_client = lark_client
    bot._started = True
    return acreate_mock


# ---------------------------------------------------------------------------
# Case 1: success — acreate 返 ok=True → 拿到 message_id
# ---------------------------------------------------------------------------

async def test_feishu_success() -> None:
    """FeishuBot.post_message 走 mock SDK 成功路径。"""
    _bootstrap_lark_sdk()
    bot = _make_feishu_bot()
    acreate_mock = _attach_mock_lark_client(
        bot,
        acreate_resp=_FakeLarkResp(
            ok=True, code=0, msg="success", message_id="om_test_001"
        ),
    )

    msg_id = await bot.post_message(chat_id="oc_test_chat", text="hello feishu")

    assert msg_id == "om_test_001", f"unexpected message_id: {msg_id!r}"
    assert acreate_mock.call_count == 1, (
        f"acreate should be called exactly once, got {acreate_mock.call_count}"
    )
    # 请求 body shape:receive_id / msg_type / content / receive_id_type
    req = acreate_mock.call_args.args[0]
    assert req.receive_id_type_v == "chat_id"
    assert req.request_body_v.msg_type_v == "text"
    # content 是 JSON 字符串 `{"text": "..."}`
    import json
    content = json.loads(req.request_body_v.content_v)
    assert content["text"] == "hello feishu"
    assert req.request_body_v.receive_id_v == "oc_test_chat"


# ---------------------------------------------------------------------------
# Case 2: APIErr — acreate 返 success=False code≠0 → SDK 抛 RuntimeError
# ---------------------------------------------------------------------------

async def test_feishu_api_err() -> None:
    """FeishuBot.post_message SDK 返 ok=False code=230002 → SDK 抛 RuntimeError。

    per 飞书 OpenAPI,常见错误:230002(no chat permission)等。
    """
    _bootstrap_lark_sdk()
    bot = _make_feishu_bot()
    acreate_mock = _attach_mock_lark_client(
        bot,
        acreate_resp=_FakeLarkResp(
            ok=False, code=230002, msg="no chat permission", message_id=""
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await bot.post_message(chat_id="oc_bad", text="will fail")

    assert "230002" in str(exc_info.value)
    # 严格 1 次 — 无 retry
    assert acreate_mock.call_count == 1, (
        f"should not retry on API error, got {acreate_mock.call_count}"
    )


# ---------------------------------------------------------------------------
# Case 3: auth_fail — app_secret 空 → start() 抛 ValueError
# ---------------------------------------------------------------------------

async def test_feishu_auth_fail() -> None:
    """FeishuBot.start() app_secret 空 → 抛 ValueError(required)。

    0 门槛 UX:app_id / app_secret 任一空立即报错(per bot.py §151)。
    """
    # auth_fail 路径不需要 SDK,直接验证 _started 守门逻辑
    bot = new_feishu_bot(
        app_id="cli_test",
        app_secret="",  # 空 secret
        builder=new_builder(),
    )

    with pytest.raises(ValueError) as exc_info:
        await bot.start()

    assert "required" in str(exc_info.value).lower()
    # 验证 bot 未启动
    assert bot._started is False
