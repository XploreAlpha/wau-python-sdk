"""OAuth 2.0 Client Credentials flow(2026-07-10 M2 OAuth Day 4)

对齐 wau-go-sdk/oauth.go:
   - OAuthClient.ClientCredentials() 走 RFC 6749 §4.4 Client Credentials grant
   - RefreshableTokenStore 自动 refresh(过期前 30s)

0 改动既有 _client.py / _transport.py / _auth.py / _options.py。
本文件独立,新增 OAuth 子模块,B 端 SDK 程序化拿 token 用。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class OAuthConfig:
    """OAuth Client Credentials 配置(B 端 SDK 程序化拿 token)

    真实用法:
       - client_id + client_secret:wau-store 注册时拿
       - scope:4 scope 之一(read:agents/write:agents/read:budgets/admin:tenant)
       - endpoint:wau-edge /oauth/token
    """

    endpoint: str  # /oauth/token URL
    client_id: str
    client_secret: str
    scope: str = ""
    refresh_skew_seconds: int = 30  # 提前 refresh


@dataclass
class _TokenPair:
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str = ""


class RefreshableTokenStore:
    """持有 access + refresh,过期前自动 refresh。线程安全。"""

    def __init__(self, pair: _TokenPair, oc: "OAuthClient") -> None:
        self._oc = oc
        self._lock = threading.RLock()
        self._access = pair.access_token
        self._refresh = pair.refresh_token
        self._expires_at = time.time() + pair.expires_in

    @property
    def access_token(self) -> str:
        with self._lock:
            return self._access

    @property
    def expires_at(self) -> float:
        with self._lock:
            return self._expires_at

    def token(self) -> str:
        """拿 access_token(过期前自动 refresh,线程安全)"""
        with self._lock:
            if time.time() + self._oc._cfg.refresh_skew_seconds < self._expires_at:
                return self._access
        # 过期 / 即将过期 → refresh(锁外做避免长持锁)
        self._refresh_access_token()
        with self._lock:
            return self._access

    def authorization_header(self) -> str:
        """返 'Bearer {access_token}' 字符串"""
        return f"Bearer {self.token()}"

    def _refresh_access_token(self) -> None:
        with self._lock:
            # 双检:可能其他线程已 refresh
            if time.time() + self._oc._cfg.refresh_skew_seconds < self._expires_at:
                return

            form: dict[str, str] = {}
            if self._refresh:
                form["grant_type"] = "refresh_token"
                form["refresh_token"] = self._refresh
                form["client_id"] = self._oc._cfg.client_id
                form["client_secret"] = self._oc._cfg.client_secret
            else:
                form["grant_type"] = "client_credentials"
                form["client_id"] = self._oc._cfg.client_id
                form["client_secret"] = self._oc._cfg.client_secret
                if self._oc._cfg.scope:
                    form["scope"] = self._oc._cfg.scope

            resp = self._oc._http.post(
                self._oc._cfg.endpoint,
                data=form,
                timeout=5,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"wau: oauth refresh HTTP {resp.status_code}: {resp.text}"
                )

            data = resp.json()
            self._access = data["access_token"]
            if data.get("refresh_token"):
                self._refresh = data["refresh_token"]
            if data.get("expires_in"):
                self._expires_at = time.time() + int(data["expires_in"])


class OAuthClient:
    """OAuth 2.0 Client Credentials 客户端(B 端 SDK 走这个)

    用法::

        oc = OAuthClient(OAuthConfig(
            endpoint="http://localhost:18400/oauth/token",
            client_id="wau-sdk-law-zhang",
            client_secret="...",
            scope="read:agents write:agents",
        ))
        store = oc.client_credentials()
        hdr = store.authorization_header()
    """

    def __init__(self, cfg: OAuthConfig, http: requests.Session | None = None) -> None:
        if not cfg.client_id:
            raise ValueError("wau: oauth client_id is required")
        if not cfg.client_secret:
            raise ValueError("wau: oauth client_secret is required")
        if not cfg.endpoint:
            raise ValueError("wau: oauth endpoint is required")
        self._cfg = cfg
        self._http = http or requests.Session()

    def client_credentials(self) -> RefreshableTokenStore:
        """走 Client Credentials grant 拿 access + refresh(per RFC 6749 §4.4)"""
        form: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._cfg.client_id,
            "client_secret": self._cfg.client_secret,
        }
        if self._cfg.scope:
            form["scope"] = self._cfg.scope

        resp = self._http.post(self._cfg.endpoint, data=form, timeout=5)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"wau: oauth HTTP {resp.status_code}: {resp.text}"
            )

        data: dict[str, Any] = resp.json()
        if not data.get("access_token"):
            raise RuntimeError("wau: oauth empty access_token in response")

        pair = _TokenPair(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data.get("expires_in", 3600)),
            refresh_token=data.get("refresh_token", ""),
            scope=data.get("scope", ""),
        )
        return RefreshableTokenStore(pair, self)