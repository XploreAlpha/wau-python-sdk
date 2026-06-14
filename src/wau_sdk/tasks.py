"""TasksService — 3 方法(对齐 wau-go-sdk tasks.go)

SubmitRequest 字段以 kernel 真相源为准({Prompt, TimeoutMs})。
"""

from __future__ import annotations

from wau_sdk._transport import AsyncTransport, Transport
from wau_sdk.types import Candidate, DecisionInfo, SubmitRequest, SubmitResponse, Task


class TasksService:
    """同步 TasksService"""

    def __init__(self, client: "Client") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: Transport = client._transport

    def submit(self, req: SubmitRequest) -> SubmitResponse:
        """POST /registry/tasks/submit (L4 真发 A2A)"""
        body: dict[str, object] = {"prompt": req.prompt}
        if req.timeout_ms is not None:
            body["timeout_ms"] = req.timeout_ms
        data = self._transport.request("POST", "/registry/tasks/submit", body=body)
        return _parse_submit_response(data)

    def simulate(self, req: SubmitRequest) -> DecisionInfo:
        """POST /registry/tasks/simulate (L3 决策,不真发)"""
        body: dict[str, object] = {"prompt": req.prompt}
        if req.timeout_ms is not None:
            body["timeout_ms"] = req.timeout_ms
        data = self._transport.request("POST", "/registry/tasks/simulate", body=body)
        return _parse_decision(data)

    def get(self, task_id: str) -> Task:
        """GET /registry/tasks/{taskID}"""
        data = self._transport.request("GET", f"/registry/tasks/{task_id}")
        return Task(**data) if data else Task(taskId=task_id)


class AsyncTasksService:
    """异步 TasksService(API 镜像)"""

    def __init__(self, client: "AsyncClient") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._transport: AsyncTransport = client._transport

    async def submit(self, req: SubmitRequest) -> SubmitResponse:
        body: dict[str, object] = {"prompt": req.prompt}
        if req.timeout_ms is not None:
            body["timeout_ms"] = req.timeout_ms
        data = await self._transport.request("POST", "/registry/tasks/submit", body=body)
        return _parse_submit_response(data)

    async def simulate(self, req: SubmitRequest) -> DecisionInfo:
        body: dict[str, object] = {"prompt": req.prompt}
        if req.timeout_ms is not None:
            body["timeout_ms"] = req.timeout_ms
        data = await self._transport.request("POST", "/registry/tasks/simulate", body=body)
        return _parse_decision(data)

    async def get(self, task_id: str) -> Task:
        data = await self._transport.request("GET", f"/registry/tasks/{task_id}")
        return Task(**data) if data else Task(taskId=task_id)


# ============================
# helpers
# ============================


def _parse_submit_response(data: dict[str, object] | None) -> SubmitResponse:
    if not data:
        return SubmitResponse()
    decision_data = data.get("decision", {}) or {}
    candidates_data = decision_data.get("candidates", []) or []
    candidates = [Candidate(**c) for c in candidates_data] if candidates_data else []
    decision = DecisionInfo(
        selected_agent=decision_data.get("selected_agent", ""),
        score=float(decision_data.get("score", 0.0)),
        decision_time_ms=int(decision_data.get("decision_time_ms", 0)),
        candidates=candidates,
    )
    dimensions = data.get("dimensions", {}) or {}
    return SubmitResponse(
        task_id=str(data.get("task_id", "")),
        agent_id=data.get("agent_id"),
        agent_url=data.get("agent_url"),
        score=float(data.get("score", 0.0)),
        dimensions={str(k): float(v) for k, v in dimensions.items()},
        decision=decision,
        status=str(data.get("status", "")),
        selected_agent=data.get("selected_agent"),
        a2a_call_ms=int(data.get("a2a_call_ms", 0)),
        response=data.get("response"),
        error=data.get("error"),
        source_peer=data.get("source_peer"),
        source_agent_id=data.get("source_agent_id"),
    )


def _parse_decision(data: dict[str, object] | None) -> DecisionInfo:
    if not data:
        return DecisionInfo()
    candidates_data = data.get("candidates", []) or []
    candidates = [Candidate(**c) for c in candidates_data] if candidates_data else []
    return DecisionInfo(
        selected_agent=str(data.get("selected_agent", "")),
        score=float(data.get("score", 0.0)),
        decision_time_ms=int(data.get("decision_time_ms", 0)),
        candidates=candidates,
    )
