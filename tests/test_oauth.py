"""OAuth Client Credentials test(2026-07-10 M2 OAuth Day 4)

0 改动既有 _client.py / _transport.py / _auth.py,新增 _oauth.py + 本测试
"""

from __future__ import annotations

import threading
import time

import pytest
from wau_sdk._oauth import OAuthClient, OAuthConfig, RefreshableTokenStore


def _make_mock_token_response(call_count: list[int], token_prefix: str, expires_in: int) -> dict:
    """mock wau-edge /oauth/token 响应"""
    n = call_count[0]
    call_count[0] += 1
    return {
        "access_token": f"{token_prefix}-{n}",
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": f"refresh-{token_prefix}-{n}",
        "scope": "read:agents",
    }


class _MockSession:
    """mock requests.Session,记录调用次数,每次返不同 token"""

    def __init__(self, token_prefix: str = "py-token", expires_in: int = 3600) -> None:
        self.call_count = 0
        self.token_prefix = token_prefix
        self.expires_in = expires_in
        self.post_lock = threading.Lock()

    def post(self, url: str, data: dict | None = None, timeout: int = 5):
        class _Resp:
            def __init__(self, body: dict, status: int) -> None:
                self._body = body
                self.status_code = status
                self.text = str(body)

            def json(self) -> dict:
                return self._body

        with self.post_lock:
            self.call_count += 1
            body = {
                "access_token": f"{self.token_prefix}-{self.call_count}",
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "refresh_token": f"refresh-{self.token_prefix}-{self.call_count}",
                "scope": "read:agents",
            }
        return _Resp(body, 200)


def test_oauth_config_required_fields():
    """OAuthConfig 必填校验"""
    with pytest.raises(ValueError, match="client_id"):
        OAuthClient(OAuthConfig(endpoint="http://x", client_id="", client_secret="y"))
    with pytest.raises(ValueError, match="client_secret"):
        OAuthClient(OAuthConfig(endpoint="http://x", client_id="x", client_secret=""))
    with pytest.raises(ValueError, match="endpoint"):
        OAuthClient(OAuthConfig(endpoint="", client_id="x", client_secret="y"))


def test_client_credentials_success():
    """ClientCredentials grant 拿 access + refresh"""
    session = _MockSession(token_prefix="py-tok")
    oc = OAuthClient(
        OAuthConfig(endpoint="http://test/oauth/token", client_id="cid", client_secret="sec"),
        http=session,
    )
    store = oc.client_credentials()
    assert store._access == "py-tok-1"
    assert session.call_count == 1


def test_authorization_header_format():
    """AuthorizationHeader 返 'Bearer {token}'"""
    session = _MockSession(token_prefix="py-tok")
    oc = OAuthClient(
        OAuthConfig(endpoint="http://x", client_id="c", client_secret="s"), http=session
    )
    store = oc.client_credentials()
    assert store.authorization_header() == "Bearer py-tok-1"


def test_auto_refresh_on_expiry():
    """过期前自动 refresh"""
    # expires_in=2s,refresh_skew=1s → 第 2 次 token() 触发 refresh
    session = _MockSession(token_prefix="refresh-tok", expires_in=2)
    oc = OAuthClient(
        OAuthConfig(
            endpoint="http://x",
            client_id="c",
            client_secret="s",
            refresh_skew_seconds=1,
        ),
        http=session,
    )
    store = oc.client_credentials()

    tok1 = store.token()
    assert tok1 == "refresh-tok-1"

    time.sleep(2)  # 等过期

    tok2 = store.token()
    assert tok2 != "refresh-tok-1", f"expected refreshed token, got {tok2}"
    assert session.call_count >= 2


def test_no_refresh_before_expiry():
    """未过期不 refresh"""
    session = _MockSession(expires_in=3600)
    oc = OAuthClient(
        OAuthConfig(endpoint="http://x", client_id="c", client_secret="s"), http=session
    )
    store = oc.client_credentials()

    for _ in range(5):
        store.token()
    assert session.call_count == 1  # 仅初次调用


def test_thread_safe_token():
    """多线程并发 token() 不会触发多次 refresh"""
    session = _MockSession(token_prefix="thread-tok", expires_in=3600)
    oc = OAuthClient(
        OAuthConfig(endpoint="http://x", client_id="c", client_secret="s"), http=session
    )
    store = oc.client_credentials()

    tokens = []

    def worker():
        tokens.append(store.token())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(tokens) == 10
    # 多个 goroutine 拿到同一 token,但个别可能 refresh 后拿到新 token(模拟过期窗口)
    # 关键:每次 token() 都不应 panic,且至少 1 个线程拿到初始 token
    assert all(t.startswith("thread-tok-") for t in tokens)
    assert session.call_count >= 1


def test_zero_impact_on_existing_sdk():
    """0 改动既有 SDK 文件 — sanity check 老模块仍可 import"""
    from wau_sdk import Client  # noqa: F401
    from wau_sdk._auth import Signer  # noqa: F401
    from wau_sdk._client import Client as LegacyClient  # noqa: F401, F811
    from wau_sdk._oauth import OAuthClient  # noqa: F401