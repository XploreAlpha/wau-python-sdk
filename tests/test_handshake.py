"""v0.8.0 M5-1 B.1 — HandshakeService 单测(respx mock kernel)

6 case(per plan §B.2):
  1. happy path(create 返 reused=False)
  2. reuse hit(同 key 再调 返 reused=True, session_id 一致)
  3. agent not found(-32002 → HandshakeAgentNotFoundError)
  4. tenant mismatch(-32003 via GetSession → HandshakeTenantMismatchError)
  5. invalid request(-32600 → HandshakeInvalidRequestError)
  6. 异步 happy path(async client)
"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import (
    ClientOptions,
    HandshakeAgentNotFoundError,
    HandshakeInvalidRequestError,
    HandshakeTenantMismatchError,
    RetryConfig,
    CircuitConfig,
)


@pytest.fixture
def client(mock_kernel: respx.MockRouter) -> wau_sdk.Client:
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        yield c


@pytest.fixture
def mock_kernel() -> respx.MockRouter:
    with respx.mock(base_url="http://mock-kernel:18400") as router:
        yield router


# ============== Case 1:happy path ==============

def test_handshake_happy(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/v0.8.0/handshake/sessions").mock(
        return_value=httpx.Response(200, json={
            "session_id": "sess-benny-1",
            "direct_endpoint": "http://benny.local:18800",
            "protocol": "a2a",
            "expires_at": "2026-06-26T20:00:00Z",
            "ttl_seconds": 300,
            "reused": False,
        })
    )
    resp = client.handshake.create_session(tenant_id="tenant-A", agent_id="Benny")
    assert resp.session_id == "sess-benny-1"
    assert resp.direct_endpoint == "http://benny.local:18800"
    assert resp.protocol == "a2a"
    assert resp.ttl_seconds == 300
    assert resp.reused is False


# ============== Case 2:reuse hit ==============

def test_handshake_reuse(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    route = mock_kernel.post("/v0.8.0/handshake/sessions").mock(
        side_effect=[
            httpx.Response(200, json={
                "session_id": "sess-benny-reuse",
                "direct_endpoint": "http://benny.local:18800",
                "protocol": "a2a",
                "expires_at": "2026-06-26T20:00:00Z",
                "ttl_seconds": 300,
                "reused": False,
            }),
            httpx.Response(200, json={
                "session_id": "sess-benny-reuse",
                "direct_endpoint": "http://benny.local:18800",
                "protocol": "a2a",
                "expires_at": "2026-06-26T20:00:00Z",
                "ttl_seconds": 300,
                "reused": True,
            }),
        ]
    )
    r1 = client.handshake.create_session(tenant_id="tenant-A", agent_id="Benny")
    r2 = client.handshake.create_session(tenant_id="tenant-A", agent_id="Benny")
    assert r1.session_id == r2.session_id == "sess-benny-reuse"
    assert r1.reused is False
    assert r2.reused is True
    assert route.call_count == 2


# ============== Case 3:agent not found ==============

def test_handshake_agent_not_found(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/v0.8.0/handshake/sessions").mock(
        return_value=httpx.Response(404, json={
            "error": {"code": -32002, "message": "agent not found in registry"}
        })
    )
    with pytest.raises(HandshakeAgentNotFoundError) as exc_info:
        client.handshake.create_session(tenant_id="tenant-A", agent_id="GhostAgent")
    assert exc_info.value.status_code == 404


# ============== Case 4:tenant mismatch(GET 时)==============

def test_handshake_tenant_mismatch(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/v0.8.0/handshake/sessions/wrong-tenant-sess").mock(
        return_value=httpx.Response(403, json={
            "error": {"code": -32003, "message": "tenant does not own this session"}
        })
    )
    with pytest.raises(HandshakeTenantMismatchError) as exc_info:
        client.handshake.get_session(session_id="wrong-tenant-sess", tenant_id="tenant-B")
    assert exc_info.value.status_code == 403


# ============== Case 5:invalid request ==============

def test_handshake_invalid_request(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/v0.8.0/handshake/sessions").mock(
        return_value=httpx.Response(400, json={
            "error": {"code": -32600, "message": "missing required fields"}
        })
    )
    with pytest.raises(HandshakeInvalidRequestError) as exc_info:
        client.handshake.create_session(tenant_id="tenant-A", agent_id="")
    assert exc_info.value.status_code == 400


# ============== Case 6:async happy path ==============

@pytest.mark.asyncio
async def test_handshake_async_happy(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.post("/v0.8.0/handshake/sessions").mock(
        return_value=httpx.Response(200, json={
            "session_id": "sess-async-1",
            "direct_endpoint": "http://benny.local:18800",
            "protocol": "a2a",
            "expires_at": "2026-06-26T20:00:00Z",
            "ttl_seconds": 300,
            "reused": False,
        })
    )
    async with wau_sdk.AsyncClient("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        resp = await c.handshake.create_session(tenant_id="tenant-A", agent_id="Benny")
    assert resp.session_id == "sess-async-1"
    assert resp.reused is False
