"""test_email_e2e.py — EmailBot mock e2e tests (W7.2 D60, 2026-07-09)

3 cases × Email (SMTP + IMAP IDLE) platform:
  1. test_email_success      — SMTP 投递成功,SDK 拿到 Message-ID
  2. test_email_api_err      — SMTP 抛 SMTPException,SDK 包成 RuntimeError
  3. test_email_auth_fail    — username/password 空 → start() 抛 ValueError

Mock 策略(per W7.2 拍板):EmailBot.post_message 内部用 stdlib smtplib.SMTP
(包 asyncio.to_thread)。aiosmtpd 不可装,我们用 unittest.mock.patch 拦截
smtplib.SMTP 构造,捕获 send_message 调用。

不真跑 IMAP IDLE — start() 仅校验 username/password 必填,业务路径在 post_message。

参考: wau-channel/internal/adapter/email/email_real_test.go。
"""
from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from wau_sdk.bot.common.options import new_builder
from wau_sdk.bot.email.bot import EmailBot, new_email_bot

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email_bot() -> EmailBot:
    return new_email_bot(
        imap_host="imap.test.example.com",
        imap_port=993,
        smtp_host="smtp.test.example.com",
        smtp_port=587,
        username="bot@test.example.com",
        password="test_app_password",
        builder=new_builder().with_tenant("acme").with_universe("us-prod"),
    )


class _FakeSMTPSession:
    """模拟 smtplib.SMTP 连接上下文管理器。

    记录 send_message 调用 + 模拟 starttls/login 成功。
    抛错模式由 raise_on_send 控制。
    """

    instances: list = []  # 每次构造 push 进来

    def __init__(self, host: str, port: int, timeout: float = 10) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sent_messages: list = []
        _FakeSMTPSession.instances.append(self)

    def __enter__(self) -> "_FakeSMTPSession":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def starttls(self, context=None) -> None:
        """模拟 STARTTLS,无操作"""
        return None

    def login(self, user: str, password: str) -> None:
        """模拟 SMTP AUTH,无操作(测试自己用 raise_on_login 模拟失败)"""
        return None

    def send_message(self, msg) -> None:
        """记录邮件内容,可选抛错"""
        self.sent_messages.append(msg)


# ---------------------------------------------------------------------------
# Case 1: success — SMTP send 成功 → SDK 拿到 Message-ID
# ---------------------------------------------------------------------------

async def test_email_success() -> None:
    """EmailBot.post_message 走 mock smtplib,SDK 拿到 Message-ID。"""
    bot = _make_email_bot()
    _FakeSMTPSession.instances.clear()

    with patch("wau_sdk.bot.email.bot.smtplib.SMTP") as mock_smtp_class:
        mock_smtp_class.side_effect = lambda *args, **kwargs: _FakeSMTPSession(
            *args, **kwargs
        )

        msg_id = await bot.post_message(
            to_address="alice@example.com",
            text="hello email",
            subject="Test Subject",
        )

    # 1. 验证 SMTP 连接被建立 1 次
    assert mock_smtp_class.call_count == 1, (
        f"smtplib.SMTP should be called exactly once, got {mock_smtp_class.call_count}"
    )
    # 2. 验证 host/port 正确
    call_args = mock_smtp_class.call_args.args
    assert call_args[0] == "smtp.test.example.com"
    assert call_args[1] == 587
    # 3. 验证邮件被发送 1 次
    assert len(_FakeSMTPSession.instances) == 1
    instance = _FakeSMTPSession.instances[0]
    assert len(instance.sent_messages) == 1, (
        f"send_message should be called once, got {len(instance.sent_messages)}"
    )
    sent_msg = instance.sent_messages[0]
    assert sent_msg["From"] == "bot@test.example.com"
    assert sent_msg["To"] == "alice@example.com"
    assert sent_msg["Subject"] == "Test Subject"
    # 4. Message-ID 非空(per RFC 2822)
    assert msg_id.startswith("<") and msg_id.endswith(">"), (
        f"msg_id should be RFC 2822 Message-ID format, got {msg_id!r}"
    )


# ---------------------------------------------------------------------------
# Case 2: APIErr — SMTP 抛 SMTPException → SDK 包成 RuntimeError
# ---------------------------------------------------------------------------

async def test_email_api_err() -> None:
    """EmailBot.post_message SMTP 抛 SMTPException → 包成 RuntimeError。"""
    bot = _make_email_bot()
    _FakeSMTPSession.instances.clear()

    class _BrokenSMTP(_FakeSMTPSession):
        def send_message(self, msg) -> None:
            raise smtplib.SMTPException("421 service not available")

    with patch("wau_sdk.bot.email.bot.smtplib.SMTP") as mock_smtp_class:
        mock_smtp_class.side_effect = lambda *args, **kwargs: _BrokenSMTP(
            *args, **kwargs
        )

        with pytest.raises(RuntimeError) as exc_info:
            await bot.post_message(
                to_address="bob@example.com", text="will fail"
            )

    # 验证 SMTP 连接只建立 1 次(无重试)
    assert mock_smtp_class.call_count == 1, (
        f"should not retry on SMTPException, got {mock_smtp_class.call_count}"
    )
    # 验证异常包了 SMTPException 信息
    assert "smtp send failed" in str(exc_info.value)
    assert "421" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Case 3: auth_fail — username/password 空 → start() 抛 ValueError
# ---------------------------------------------------------------------------

async def test_email_auth_fail() -> None:
    """EmailBot.start() username/password 空 → 抛 ValueError(required)。

    0 门槛 UX:imap_host / username / password 任一空立即报错(per bot.py §155)。
    """
    bot = new_email_bot(
        imap_host="imap.test.example.com",
        imap_port=993,
        smtp_host="smtp.test.example.com",
        smtp_port=587,
        username="",
        password="",  # 双空
        builder=new_builder(),
    )

    with pytest.raises(ValueError) as exc_info:
        await bot.start()

    assert "required" in str(exc_info.value).lower()
    # bot 未启动
    assert bot._started is False
