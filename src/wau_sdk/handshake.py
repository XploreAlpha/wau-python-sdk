"""HandshakeService — 对齐 WAU-core-kernel M1 握手端点(同步 + 异步)

v0.8.0 M5-1 B.1:4 SDK handshake client 联调。

对应 kernel 端点(per WAU-core-kernel/cmd/wau-core/handle_handshake.go):
  - POST /v0.8.0/handshake/sessions
  - GET  /v0.8.0/handshake/sessions/{session_id}?tenant_id=xxx
  - GET  /admin/handshake/stats

DTO 字段 1:1 对齐 kernel internal/handshake/session.go:92-142。
错误码 9 个走 _errors.py 新增 HandshakeError 子类工厂。
"""

from __future__ import annotations

from wau_sdk._errors import (
    HandshakeAgentNoEndpointError,
    HandshakeAgentNotFoundError,
    HandshakeInsufficientTrustError,
    HandshakeInvalidProtocolError,
    HandshakeInvalidRequestError,
    HandshakeProtocolNotSupportedError,
    HandshakeRateLimitedError,
    HandshakeSessionNotFoundError,
    HandshakeTenantMismatchError,
)
from wau_sdk.types import (
    HandshakeRequest,
    HandshakeResponse,
    HandshakeSessionDetail,
    HandshakeStats,
)


class HandshakeService:
    """同步 HandshakeService — 3 个方法(create/get/stats)

    用法::

        with wau_sdk.Client("http://localhost:18400") as c:
            resp = c.handshake.create_session(tenant_id="tenant-A", agent_id="Benny")
    """

    def __init__(self, client) -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport = client._transport
        self._options = client.options

    def create_session(
        self,
        tenant_id: str,
        agent_id: str,
        protocol: str = "a2a",
        universe: str = "",
        client_id: str = "",
    ) -> HandshakeResponse:
        """POST /v0.8.0/handshake/sessions

        client_id 不传时自动用 SDK user_agent。
        """
        body: dict[str, str] = {
            "tenant_id": tenant_id,
            "client_id": client_id or self._options.user_agent,
            "agent_id": agent_id,
            "protocol": protocol,
        }
        if universe:
            body["universe"] = universe
        data = self._transport.request("POST", "/v0.8.0/handshake/sessions", body=body)
        return HandshakeResponse(**data)

    def get_session(self, session_id: str, tenant_id: str) -> HandshakeSessionDetail:
        """GET /v0.8.0/handshake/sessions/{session_id}?tenant_id=xxx

        tenant_id 必须传,用于跨 tenant 防护。
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for get_session")
        data = self._transport.request(
            "GET", f"/v0.8.0/handshake/sessions/{session_id}", params={"tenant_id": tenant_id}
        )
        return HandshakeSessionDetail(**data)

    def get_stats(self) -> HandshakeStats:
        """GET /admin/handshake/stats — hit rate 监控"""
        data = self._transport.request("GET", "/admin/handshake/stats")
        return HandshakeStats(**data)


class AsyncHandshakeService:
    """异步 HandshakeService(API 镜像同步版)"""

    def __init__(self, client) -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport = client._transport
        self._options = client.options

    async def create_session(
        self,
        tenant_id: str,
        agent_id: str,
        protocol: str = "a2a",
        universe: str = "",
        client_id: str = "",
    ) -> HandshakeResponse:
        body: dict[str, str] = {
            "tenant_id": tenant_id,
            "client_id": client_id or self._options.user_agent,
            "agent_id": agent_id,
            "protocol": protocol,
        }
        if universe:
            body["universe"] = universe
        data = await self._transport.request("POST", "/v0.8.0/handshake/sessions", body=body)
        return HandshakeResponse(**data)

    async def get_session(self, session_id: str, tenant_id: str) -> HandshakeSessionDetail:
        if not tenant_id:
            raise ValueError("tenant_id is required for get_session")
        data = await self._transport.request(
            "GET", f"/v0.8.0/handshake/sessions/{session_id}", params={"tenant_id": tenant_id}
        )
        return HandshakeSessionDetail(**data)

    async def get_stats(self) -> HandshakeStats:
        data = await self._transport.request("GET", "/admin/handshake/stats")
        return HandshakeStats(**data)
