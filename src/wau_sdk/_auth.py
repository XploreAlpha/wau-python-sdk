"""HS256 鉴权 — 对齐 wau-a2a-gateway + wau-go-sdk auth.go

JWT 结构:
{
  "agent": "my-agent",
  "role":  "trusted_agent",
  "iat":   1718342400,
  "exp":   1718342700,    # iat + 300s (5 min)
  "jti":   "uuid-v4"
}
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
        self._secret = auth.shared_secret
        self._agent_name = auth.agent_name
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
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")
