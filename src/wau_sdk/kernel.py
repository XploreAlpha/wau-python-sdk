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
        if not data:
            return KernelInfo(version="unknown", startTime="", uptime=0, agentsCount=0, tasksCount=0)
        # 字段名转换: kernel 返 camelCase (startTime), Python 用 snake_case
        return KernelInfo(
            version=data.get("version", "unknown"),
            startTime=data.get("startTime", ""),
            uptime=int(data.get("uptime", 0)),
            agentsCount=int(data.get("agentsCount", 0)),
            tasksCount=int(data.get("tasksCount", 0)),
        )

    def health(self) -> HealthResponse:
        """GET /health"""
        data = self._transport.request("GET", "/health")
        if not data:
            return HealthResponse(status="unknown")
        return HealthResponse(
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            uptime=float(data.get("uptime", 0.0)),
            redis=data.get("redis", ""),
            error=data.get("error"),
        )


class AsyncKernelService:
    """异步 KernelService"""

    def __init__(self, client: "AsyncClient") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: AsyncTransport = client._transport

    async def info(self) -> KernelInfo:
        data = await self._transport.request("GET", "/kernel/info")
        if not data:
            return KernelInfo(version="unknown", startTime="", uptime=0, agentsCount=0, tasksCount=0)
        return KernelInfo(
            version=data.get("version", "unknown"),
            startTime=data.get("startTime", ""),
            uptime=int(data.get("uptime", 0)),
            agentsCount=int(data.get("agentsCount", 0)),
            tasksCount=int(data.get("tasksCount", 0)),
        )

    async def health(self) -> HealthResponse:
        data = await self._transport.request("GET", "/health")
        if not data:
            return HealthResponse(status="unknown")
        return HealthResponse(
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            uptime=float(data.get("uptime", 0.0)),
            redis=data.get("redis", ""),
            error=data.get("error"),
        )
