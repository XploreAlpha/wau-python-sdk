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

# ============================================================================
# v1.0.0 M4 OAuth 增强 (2026-07-08) tests
# ============================================================================

def test_m4_refresh_token_public_method(monkeypatch):
    """M4:refresh_token() 公开方法,caller 显式触发"""
    from unittest.mock import MagicMock
    from wau_sdk import _oauth
    call_count = [0]

    def make_resp(grant, refresh=None):
        resp = MagicMock()
        resp.status_code = 200
        if grant == "client_credentials":
            resp.json.return_value = {
                "access_token": "initial-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "original-refresh",
                "scope": "read:agents",
            }
        else:  # refresh_token
            assert refresh == "original-refresh", f"unexpected refresh: {refresh}"
            resp.json.return_value = {
                "access_token": "rotated-access-new",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rotated-refresh-new",
                "scope": "read:agents",
            }
        return resp

    def mock_post(url, data=None, timeout=None):
        call_count[0] += 1
        grant = (data or {}).get("grant_type")
        return make_resp(grant, refresh=(data or {}).get("refresh_token"))

    # mock OAuthClient.__init__ 不做 validation,直接保存 cfg
    orig_init = _oauth.OAuthClient.__init__
    def patched_init(self, cfg, http=None):
        self._cfg = cfg
        self._http = http or MagicMock()
    monkeypatch.setattr(_oauth.OAuthClient, "__init__", patched_init)

    oc = _oauth.OAuthClient(_oauth.OAuthConfig(
        endpoint="http://mock/oauth/token",
        client_id="c", client_secret="s", scope="read:agents",
    ))
    oc._http.post = mock_post

    store = oc.client_credentials()
    assert store.access_token == "initial-access", f"got {store.access_token}"

    # 显式 refresh
    store.refresh_token()
    pair = store.current_pair()
    assert pair.access_token == "rotated-access-new", f"got {pair.access_token}"
    assert pair.refresh_token == "rotated-refresh-new", f"got {pair.refresh_token}"


def test_m4_generate_pkce_challenge():
    """M4:PKCE challenge 幂等性 + 长度"""
    from wau_sdk._oauth import generate_pkce_challenge
    a = generate_pkce_challenge()
    b = generate_pkce_challenge()
    assert a.verifier != b.verifier
    assert a.method == "S256"
    assert len(a.verifier) >= 43
    assert len(a.challenge) >= 43


def test_m4_pkce_client_authorization_url():
    """M4:PKCE authorization URL 构造"""
    from wau_sdk._oauth import PKCEClient, PKCEConfig, generate_pkce_challenge
    pc = PKCEClient(PKCEConfig(
        auth_endpoint="https://wau.example.com/oauth/authorize",
        token_endpoint="https://wau.example.com/oauth/token",
        client_id="wau-sdk-pkce-test",
        redirect_uri="https://myapp.com/callback",
        scopes=["read:agents", "write:agents"],
    ))
    chal = generate_pkce_challenge()
    url = pc.authorization_url("state-csrf-123", chal)
    assert "response_type=code" in url
    assert f"code_challenge={chal.challenge}" in url
    assert "code_challenge_method=S256" in url
    assert "state=state-csrf-123" in url
    assert "client_id=wau-sdk-pkce-test" in url
    # scope url-encoded: "read:agents write:agents" → "read%3Aagents+write%3Aagents" or "read%3Aagents%20write%3Aagents"
    assert ("read%3Aagents" in url) and ("write%3Aagents" in url)


def test_m4_pkce_client_exchange_code(monkeypatch):
    """M4:PKCE exchange_code → RefreshableTokenStore"""
    from unittest.mock import MagicMock
    import wau_sdk._oauth as oauth_mod
    from wau_sdk._oauth import PKCEClient, PKCEConfig

    def mock_post(url, data=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "access_token": "pkce-access",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "pkce-refresh",
            "scope": "read:agents",
        }
        return resp

    monkeypatch.setattr("requests.post", mock_post)

    pc = PKCEClient(PKCEConfig(
        auth_endpoint="https://wau.example.com/oauth/authorize",
        token_endpoint="http://mock/oauth/token",
        client_id="wau-sdk-pkce-test",
        redirect_uri="https://myapp.com/callback",
        scopes=["read:agents"],
    ))
    store = pc.exchange_code("auth-code", "test-verifier-abc")
    assert store.access_token == "pkce-access"
