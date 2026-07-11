"""MCP auth helpers (wau-python-sdk v1.3.2, per D87.6).

Bearer token 注入 helper(per D78/D79/D80 + W3-MCP-auth-SDK-design §三)。
"""

from __future__ import annotations

from typing import Optional

# Auth header 常量
AUTH_HEADER_NAME = "Authorization"
AUTH_SCHEME_PREFIX = "Bearer "
DEFAULT_USER_AGENT = "wau-python-sdk/mcpclient/v1.3.2"


def set_bearer_token(headers: dict, token: str) -> dict:
    """注入 Authorization: Bearer <token> 到 headers(per D78/D79)。"""
    if token:
        headers[AUTH_HEADER_NAME] = AUTH_SCHEME_PREFIX + token
    elif AUTH_HEADER_NAME in headers:
        del headers[AUTH_HEADER_NAME]
    return headers


def build_headers(
    bearer_token: Optional[str] = None,
    user_agent: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """构造 MCP request headers (Content-Type + User-Agent + Authorization)。"""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
    }
    if bearer_token:
        set_bearer_token(h, bearer_token)
    if extra:
        h.update(extra)
    return h