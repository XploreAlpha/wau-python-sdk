"""DTO 定义 — 跟 wau-go-sdk types.go 字段 1:1 对应
所有字段以 WAU-core-kernel 真相源为准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthResponse:
    status: str
    version: str
    uptime: float
    redis: str
    error: str | None = None


@dataclass
class KernelInfo:
    version: str
    startTime: str
    uptime: int
    agentsCount: int
    tasksCount: int


@dataclass
class Agent:
    name: str
    id: str = ""
    url: str = ""
    description: str = ""
    skills: list[str] = field(default_factory=list)
    universes: list[str] = field(default_factory=list)
    trust: float = 0.0
    status: str = ""
    lastSeen: str = ""


@dataclass
class AgentListResponse:
    agents: list[Agent] = field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = 10
    totalPages: int = 1


@dataclass
class PageOptions:
    """分页 + 过滤参数(对齐 Go SDK PageOptions)"""
    page: int = 1           # 1-based
    pageSize: int = 10      # max 100
    skill: str | None = None
    status: str | None = None
    search: str | None = None


@dataclass
class PageResult[T]:
    """通用分页结果(泛型,Go 1.23+ 等价物)"""
    items: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = 10
    totalPages: int = 1


@dataclass
class AgentRegisterRequest:
    name: str
    url: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    universes: list[str] = field(default_factory=list)


@dataclass
class AgentScore:
    name: str
    totalScore: float = 0.0
    trustScore: float = 0.0
    skillMatch: float = 0.0
    healthScore: float = 0.0
    loadScore: float = 0.0


@dataclass
class AgentLoad:
    activeTasks: int = 0
    maxCapacity: int = 10
    cpuUsage: float = 0.0
    memoryUsage: float = 0.0


@dataclass
class AgentStatus:
    name: str
    status: str
    trust: float = 0.0
    load: AgentLoad = field(default_factory=AgentLoad)
    circuit: str = "closed"


@dataclass
class Task:
    taskId: str
    message: str = ""
    sourcePeer: str = ""
    sourceAgentId: str | None = None
    status: str = ""
    assignedAgent: str | None = None
    result: str | None = None
    createdAt: int = 0
    updatedAt: int = 0
    requiredSkills: list[str] = field(default_factory=list)


@dataclass
class SubmitRequest:
    """L4 提交请求 — 字段以 kernel 真相源为准(Prompt + TimeoutMs)

    v0.6.0 M3 W6 关键修正:wau-cli 旧 DTO {message, sourcePeer, ...} 跟 kernel 不一致,
    SDK 以 kernel 真相源为准。参见 ADR-0001/0002。
    """
    prompt: str
    timeout_ms: int | None = None


@dataclass
class Candidate:
    name: str
    score: float = 0.0
    reason: str = ""


@dataclass
class DecisionInfo:
    selected_agent: str = ""
    score: float = 0.0
    decision_time_ms: int = 0
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class SubmitResponse:
    task_id: str = ""
    agent_id: str | None = None
    agent_url: str | None = None
    score: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    decision: DecisionInfo = field(default_factory=DecisionInfo)
    status: str = ""
    selected_agent: str | None = None
    a2a_call_ms: int = 0
    response: Any = None
    error: str | None = None
    source_peer: str | None = None
    source_agent_id: str | None = None


@dataclass
class IntentDTO:
    """可选 intent hint (L3)"""
    type: str = ""
    requiredSkills: list[str] = field(default_factory=list)
    urgency: str = ""
    estimatedComplexity: int = 0
