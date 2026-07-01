"""HS256 鉴权 — 对齐 wau-a2a-gateway + wau-go-sdk auth.go

JWT 结构:
{
  "agent":     "my-agent",
  "role":      "trusted_agent",
  "sub":       "user-id-or-agent",
  "tenant_id": "tenant-A",
  "iat":       1718342400,
  "exp":       1718342700,    # iat + 300s (5 min)
  "jti":       "uuid-v4"
}

per Stage 3.1 #1 修复(2026-07-01):wau-edge Claims 必填 tenant_id(per
wau-edge/internal/auth/jwt.go:96-98),SDK 必须签。Subject 对齐 sub claim。
"""

from __future__ import annotations

import uuid
from typing import Any

import jwt

from wau_sdk._options import AuthConfig


class Signer:
    """HS256 JWT 签发器(对齐 wau-go-sdk signer)"""

    def __init__(self, auth: AuthConfig) -> None:
        if not auth.shared_secret:
            raise ValueError("wau: auth.shared_secret is required for HS256")
        if not auth.agent_name:
            raise ValueError("wau: auth.agent_name is required")
        if not auth.tenant_id:
            raise ValueError("wau: auth.tenant_id is required (wau-edge Claims 必填)")
        self._secret = auth.shared_secret
        self._agent_name = auth.agent_name
        self._tenant_id = auth.tenant_id
        # Subject 兜底:空时用 agent_name(per Go SDK 同款兜底)
        self._subject = auth.subject or auth.agent_name
        self._role = auth.role.value if hasattr(auth.role, "value") else str(auth.role)

    @property
    def role(self) -> str:
        return self._role

    def sign(self, ttl_seconds: int = 300) -> str:
        """签一个新 JWT(默认 5 分钟过期,UUID v4 jti 防重放)

        Args:
            ttl_seconds: 过期秒数(默认 300 = 5 min)

        Returns:
            编码后的 JWT 字符串
        """
        import time

        now = int(time.time())
        payload: dict[str, Any] = {
            "agent": self._agent_name,
            "role": self._role,
            "sub": self._subject,
            "tenant_id": self._tenant_id,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")
