"""KernelService 单测 — 2 方法(respx mock kernel)"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import ClientOptions, RetryConfig, CircuitConfig


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


def test_kernel_info(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/kernel/info").mock(
        return_value=httpx.Response(200, json={
            "version": "v0.6.0", "startTime": "2026-06-14T00:00:00Z",
            "uptime": 60, "agentsCount": 3, "tasksCount": 5,
        })
    )
    info = client.kernel.info()
    assert info.version == "v0.6.0"
    assert info.agentsCount == 3
    assert info.tasksCount == 5


def test_kernel_health(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/health").mock(
        return_value=httpx.Response(200, json={
            "status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected",
        })
    )
    health = client.kernel.health()
    assert health.status == "ok"


def test_kernel_health_500(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/health").mock(
        return_value=httpx.Response(500, json={"error": "redis down"})
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        with pytest.raises(wau_sdk.APIError):
            c.kernel.health()


def test_kernel_info_unauthorized(mock_kernel: respx.MockRouter) -> None:
    mock_kernel.get("/kernel/info").mock(
        return_value=httpx.Response(401, json={"error": "invalid token", "code": "unauthorized"})
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        with pytest.raises(wau_sdk.UnauthorizedError):
            c.kernel.info()
