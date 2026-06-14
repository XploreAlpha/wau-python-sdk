"""AgentsService — 7 方法(对齐 wau-go-sdk agents.go)"""

from __future__ import annotations

from typing import Iterator

from wau_sdk._transport import AsyncTransport, Transport
from wau_sdk.types import (
    Agent,
    AgentListResponse,
    AgentLoad,
    AgentRegisterRequest,
    AgentScore,
    AgentStatus,
    HealthResponse,
    PageOptions,
)


class AgentsService:
    """同步 AgentsService — 7 个 CRUD/状态/评分/心跳/负载方法"""

    def __init__(self, client: "Client") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: Transport = client._transport

    # ---- Health ----

    def health(self) -> HealthResponse:
        """GET /health"""
        data = self._transport.request("GET", "/health")
        return HealthResponse(**data) if data else HealthResponse(status="unknown")

    # ---- List / Iter ----

    def list(self, opts: PageOptions | None = None) -> AgentListResponse:
        """GET /registry/agents?page=...&pageSize=...&skill=...&status=...&search=..."""
        opts = opts or PageOptions()
        params: dict[str, str | int] = {
            "page": max(1, opts.page),
            "pageSize": max(1, min(100, opts.pageSize)),
        }
        if opts.skill:
            params["skill"] = opts.skill
        if opts.status:
            params["status"] = opts.status
        if opts.search:
            params["search"] = opts.search
        data = self._transport.request("GET", "/registry/agents", params=params)
        resp = AgentListResponse(**data)
        # 嵌套 dict → Agent dataclass
        if resp.agents:
            resp.agents = [Agent(**a) if isinstance(a, dict) else a for a in resp.agents]
        return resp

    def iter(self, opts: PageOptions | None = None) -> Iterator[Agent]:
        """迭代所有页(分页懒加载)"""
        opts = opts or PageOptions()
        opts.page = 1
        if opts.pageSize <= 0:
            opts.pageSize = 10
        while True:
            page = self.list(opts)
            for a in page.agents:
                yield a
            if opts.page >= page.totalPages:
                return
            opts.page += 1

    # ---- Single agent operations ----

    def get(self, name: str) -> AgentStatus:
        """GET /registry/agents/{name}/status"""
        data = self._transport.request("GET", f"/registry/agents/{name}/status")
        if not data:
            return AgentStatus(name=name, status="unknown")
        # 处理嵌套 load 字段(kernel 返 dict,需要转 AgentLoad)
        load_data = data.get("load", {}) or {}
        if isinstance(load_data, dict):
            data = {**data, "load": AgentLoad(**load_data)}
        return AgentStatus(**data)

    def score(self, name: str) -> AgentScore:
        """GET /registry/agents/{name}/score"""
        data = self._transport.request("GET", f"/registry/agents/{name}/score")
        return AgentScore(**data) if data else AgentScore(name=name)

    # ---- Registration ----

    def register(self, req: AgentRegisterRequest) -> None:
        """POST /registry/agents/register (RBAC: trusted_agent / kernel_core)"""
        self._transport.request("POST", "/registry/agents/register", body={
            "name": req.name,
            "url": req.url,
            "description": req.description,
            "skills": req.skills,
            "universes": req.universes,
        })

    def deregister(self, name: str) -> None:
        """DELETE /registry/agents/{name}"""
        self._transport.request("DELETE", f"/registry/agents/{name}")

    # ---- Heartbeat / Load ----

    def heartbeat(self, agent_id: str) -> None:
        """POST /registry/agents/heartbeat"""
        self._transport.request("POST", "/registry/agents/heartbeat", body={"agentId": agent_id})

    def report_load(self, agent_id: str, load: AgentLoad) -> None:
        """POST /heartbeat/load"""
        self._transport.request("POST", "/heartbeat/load", body={
            "agentId": agent_id,
            "activeTasks": load.activeTasks,
            "maxCapacity": load.maxCapacity,
            "cpuUsage": load.cpuUsage,
            "memoryUsage": load.memoryUsage,
        })


class AsyncAgentsService:
    """异步 AgentsService(API 镜像同步版)"""

    def __init__(self, client: "AsyncClient") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: AsyncTransport = client._transport

    async def health(self) -> HealthResponse:
        data = await self._transport.request("GET", "/health")
        return HealthResponse(**data) if data else HealthResponse(status="unknown")

    async def list(self, opts: PageOptions | None = None) -> AgentListResponse:
        opts = opts or PageOptions()
        params: dict[str, str | int] = {
            "page": max(1, opts.page),
            "pageSize": max(1, min(100, opts.pageSize)),
        }
        if opts.skill:
            params["skill"] = opts.skill
        if opts.status:
            params["status"] = opts.status
        if opts.search:
            params["search"] = opts.search
        data = await self._transport.request("GET", "/registry/agents", params=params)
        resp = AgentListResponse(**data)
        if resp.agents:
            resp.agents = [Agent(**a) if isinstance(a, dict) else a for a in resp.agents]
        return resp

    async def get(self, name: str) -> AgentStatus:
        data = await self._transport.request("GET", f"/registry/agents/{name}/status")
        if not data:
            return AgentStatus(name=name, status="unknown")
        load_data = data.get("load", {}) or {}
        if isinstance(load_data, dict):
            data = {**data, "load": AgentLoad(**load_data)}
        return AgentStatus(**data)

    async def score(self, name: str) -> AgentScore:
        data = await self._transport.request("GET", f"/registry/agents/{name}/score")
        return AgentScore(**data) if data else AgentScore(name=name)

    async def register(self, req: AgentRegisterRequest) -> None:
        await self._transport.request("POST", "/registry/agents/register", body={
            "name": req.name, "url": req.url, "description": req.description,
            "skills": req.skills, "universes": req.universes,
        })

    async def deregister(self, name: str) -> None:
        await self._transport.request("DELETE", f"/registry/agents/{name}")

    async def heartbeat(self, agent_id: str) -> None:
        await self._transport.request("POST", "/registry/agents/heartbeat", body={"agentId": agent_id})

    async def report_load(self, agent_id: str, load: AgentLoad) -> None:
        await self._transport.request("POST", "/heartbeat/load", body={
            "agentId": agent_id,
            "activeTasks": load.activeTasks,
            "maxCapacity": load.maxCapacity,
            "cpuUsage": load.cpuUsage,
            "memoryUsage": load.memoryUsage,
        })
