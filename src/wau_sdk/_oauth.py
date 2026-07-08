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

    # v1.0.0 M4 — Refresh 公开方法 + CurrentPair
    def refresh_token(self) -> None:
        """显式触发 refresh(per RFC 6749 §6),force=True 绕过双检。"""
        self._refresh_access_token(force=True)

    def current_pair(self) -> "TokenPair":
        """返当前 token pair(明文,谨慎使用)。"""
        with self._lock:
            return TokenPair(
                access_token=self._access,
                token_type=getattr(self, "_token_type", "Bearer"),
                expires_in=int(self._expires_at - time.time()),
                refresh_token=self._refresh,
                scope=getattr(self, "_scope", ""),
            )

    def _refresh_access_token(self, force: bool = False) -> None:
        with self._lock:
            # 双检:可能其他线程已 refresh(force=True 跳过)
            if not force and time.time() + self._oc._cfg.refresh_skew_seconds < self._expires_at:
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

# ============================================================================
# v1.0.0 M4 OAuth 增强 (2026-07-08):Refresh 公开方法 + PKCE
# 设计(per M4 拍板 2.1=A Server side + 2.2=A Rotate + 2.3=A 4 SDK 都加):
#   - refresh_token() 公开方法:caller 显式触发 refresh(不等 token() lazy)
#   - current_pair() 返 TokenPair dataclass(给 caller 持久化)
#   - PKCEClient:Authorization Code + PKCE(per RFC 7636)
#   - 0 改老 OAuthClient + RefreshableTokenStore(D60 additive)
# ============================================================================

import base64
import hashlib
import os
import secrets
import urllib.parse
from dataclasses import dataclass


@dataclass
class TokenPair:
    """公开 access + refresh 明文(给 caller 持久化用,如存到文件/secret manager)。
    
    安全注意:refresh_token 明文只能返 1 次,client 拿到后立刻持久化,不要 log。
    """
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str = ""


# v1.0.0 M4 — refresh_token + current_pair 已在 RefreshableTokenStore 内定义(类内,见 L80+)


# ---------------------- PKCE(per RFC 7636) ----------------------

@dataclass
class PKCEConfig:
    """PKCE(per RFC 7636)配置。公共 client(无 client_secret)用这个走 Auth Code flow。"""
    auth_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    scopes: list[str]


@dataclass
class PKCEChallenge:
    """PKCE code_verifier + code_challenge(S256 模式)。"""
    verifier: str
    challenge: str
    method: str  # "S256"


def generate_pkce_challenge() -> PKCEChallenge:
    """生成 code_verifier(43-128 字符)+ code_challenge(S256 哈希 base64url)。
    
    per RFC 7636 §4.1:verifier 用 32-512 bits 随机数,base64url 编码
    per RFC 7636 §4.2:challenge = base64url(SHA256(verifier))
    """
    # 32 bytes → 43 字符 base64url no padding
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")
    # S256:challenge = base64url(sha256(verifier))
    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode("ascii")
    return PKCEChallenge(verifier=verifier, challenge=challenge, method="S256")


class PKCEClient:
    """Authorization Code + PKCE 客户端(per OAuth 2.0 + RFC 7636)。
    
    流程:
      1. authorization_url(state, challenge) → 返 URL,caller 让用户在浏览器打开
      2. 用户授权后,wau-store 重定向到 redirect_uri?code=...&state=...
      3. exchange_code(code, verifier) → 拿 RefreshableTokenStore
    
    公共 client(无 client_secret)安全保护:code_verifier 只在 client 内存,不被截获。
    """
    
    def __init__(self, cfg: PKCEConfig) -> None:
        if not cfg.auth_endpoint:
            raise ValueError("wau: PKCE auth_endpoint is required")
        if not cfg.token_endpoint:
            raise ValueError("wau: PKCE token_endpoint is required")
        if not cfg.client_id:
            raise ValueError("wau: PKCE client_id is required")
        if not cfg.redirect_uri:
            raise ValueError("wau: PKCE redirect_uri is required")
        self._cfg = cfg
    
    def authorization_url(self, state: str, challenge: PKCEChallenge) -> str:
        """构造 authorize URL(用户浏览器打开)。
        
        包含 PKCE code_challenge + state(caller 注入用于防 CSRF)。
        """
        params = {
            "response_type": "code",
            "client_id": self._cfg.client_id,
            "redirect_uri": self._cfg.redirect_uri,
            "scope": " ".join(self._cfg.scopes),
            "state": state,
            "code_challenge": challenge.challenge,
            "code_challenge_method": challenge.method,
        }
        qs = urllib.parse.urlencode(params)
        return f"{self._cfg.auth_endpoint}?{qs}"
    
    def exchange_code(self, code: str, verifier: str) -> RefreshableTokenStore:
        """用 authorization code + code_verifier 换 token pair(per RFC 6749 §4.1.3 + RFC 7636 §4.5)。"""
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
            "client_id": self._cfg.client_id,
            "code_verifier": verifier,
        }
        resp = requests.post(self._cfg.token_endpoint, data=form, timeout=5)
        if resp.status_code >= 400:
            raise RuntimeError(f"wau: PKCE exchange HTTP {resp.status_code}: {resp.text}")
        
        data = resp.json()
        if not data.get("access_token"):
            raise RuntimeError("wau: PKCE exchange empty access_token")
        
        pair = _TokenPair(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data.get("expires_in", 3600)),
            refresh_token=data.get("refresh_token", ""),
            scope=data.get("scope", ""),
        )
        # PKCE 路径:不构造 OAuthClient(公共 client 无 secret)
        # store 不会有 oc.refresh_token 调用(因为是 no secret 场景)
        # 用一个 wrapper 持有 oc=None 的 store(简化:把 refresh_token 写入 store,token() 走 cache 路径)
        return _PKCEOnlyStore(pair)



class _PKCEOnlyStore:
    """PKCE 专用 store,无 oc 引用,Token() 直接返明文 access(简化版)。
    
    区别:本 store 不持有 oc,无法 refresh。caller 需要重新走 exchange_code 拿新 token。
    """
    def __init__(self, pair: _TokenPair) -> None:
        self._access = pair.access_token
        self._refresh = pair.refresh_token
        self._token_type = pair.token_type
        self._scope = pair.scope
        self._expires_at = time.time() + pair.expires_in
    
    @property
    def access_token(self) -> str:
        return self._access
    
    def token(self) -> str:
        return self._access
    
    def current_pair(self) -> TokenPair:
        return TokenPair(
            access_token=self._access,
            token_type=self._token_type,
            expires_in=int(self._expires_at - time.time()),
            refresh_token=self._refresh,
            scope=self._scope,
        )
