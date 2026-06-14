"""KernelService — 2 方法(对齐 wau-go-sdk kernel.go)"""

from __future__ import annotations

from wau_sdk._transport import AsyncTransport, Transport
from wau_sdk.types import HealthResponse, KernelInfo


class KernelService:
    """同步 KernelService"""

    def __init__(self, client: "Client") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: Transport = client._transport

    def info(self) -> KernelInfo:
        """GET /kernel/info"""
        data = self._transport.request("GET", "/kernel/info")
        return KernelInfo(**data) if data else KernelInfo(version="unknown", startTime="", uptime=0, agentsCount=0, tasksCount=0)

    def health(self) -> HealthResponse:
        """GET /health"""
        data = self._transport.request("GET", "/health")
        return HealthResponse(**data) if data else HealthResponse(status="unknown")


class AsyncKernelService:
    """异步 KernelService"""

    def __init__(self, client: "AsyncClient") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: AsyncTransport = client._transport

    async def info(self) -> KernelInfo:
        data = await self._transport.request("GET", "/kernel/info")
        return KernelInfo(**data) if data else KernelInfo(version="unknown", startTime="", uptime=0, agentsCount=0, tasksCount=0)

    async def health(self) -> HealthResponse:
        data = await self._transport.request("GET", "/health")
        return HealthResponse(**data) if data else HealthResponse(status="unknown")
