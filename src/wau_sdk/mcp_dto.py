"""MCP DTOs (wau-python-sdk v1.3.2, per D87.6).

8 DTOs aligned byte-equal to:
  - kernel `internal/protocol/mcp/handler.go` response shapes
  - wau-go-sdk `mcpclient/types.go` (v1.3.2, cross-SDK D13 byte-equal)
  - design doc [[process/2026-07-10-W3-MCP-client-SDK-design]] §二

JSON field names use snake_case (per MCP spec + JSON-RPC 2.0 wire format).

8 sync DTOs (对应 kernel mcp/tools.go 8 sync tool,2 SSE tool deferred to W5+):
  - Message / Part (send_message / parse_agent_card input)
  - Task / Artifact (send_message / get_task / cancel_task output)
  - AgentCard (parse_agent_card output)
  - HealthCheckResult (health_check output)
  - ExtendedAgentCard (get_extended_agent_card output)
  - ListTasksFilter + ListTasksResult (list_tasks output)
  - PushConfig + PushConfigResult (create_task_push_notification_config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ────────────────────────────────────────────────────────
# send_message / parse_agent_card input
# ────────────────────────────────────────────────────────

@dataclass
class Part:
    """Message part (MCP content types: text / file / data)."""

    type: str = "text"          # "text" | "file" | "data"
    text: Optional[str] = None
    file: Optional[dict] = None  # {"name", "mimeType", "bytes"|"uri"}
    data: Optional[dict] = None  # arbitrary structured data


@dataclass
class Message:
    """MCP message (send_message input).

    Per design doc §二.2.3 (tool 3),message 包含 role + parts + 可选 context_id + metadata。
    """

    role: str = "user"           # "user" | "agent" | "system"
    parts: list[Part] = field(default_factory=list)
    context_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ────────────────────────────────────────────────────────
# Task (send_message / get_task / cancel_task output)
# ────────────────────────────────────────────────────────

@dataclass
class Artifact:
    """Task artifact (MCP-A2A aligned shape)."""

    type: str = "text"
    text: Optional[str] = None
    file: Optional[dict] = None
    data: Optional[dict] = None


@dataclass
class Task:
    """Task status + artifacts (对应 send_message / get_task / cancel_task result).

    字段对齐 kernel handler.responseToMap(per D87.1 server.go)。
    """

    task_id: Optional[str] = None
    context_id: Optional[str] = None
    status: str = "completed"     # "working" | "completed" | "failed" | "canceled"
    artifacts: list[Artifact] = field(default_factory=list)
    canceled_at: Optional[str] = None
    history: list[dict] = field(default_factory=list)  # TaskState 历史(send_message 暂不返)


# ────────────────────────────────────────────────────────
# Agent card (parse_agent_card / get_extended_agent_card output)
# ────────────────────────────────────────────────────────

@dataclass
class AgentCard:
    """Agent self-description card(per design doc §二.2.3 tool 2)。

    包含 name / version / description / supported_interfaces / skills / trust_score 等。
    """

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    supported_interfaces: list[str] = field(default_factory=list)  # e.g. ["a2a", "afp", "mcp", "ucp"]
    skills: list[str] = field(default_factory=list)
    url: Optional[str] = None
    provider: Optional[str] = None
    documentation_url: Optional[str] = None


@dataclass
class ExtendedAgentCard:
    """Extended agent card (per design doc §二.2.3 tool 10)。

    跟 AgentCard 类似但含私有字段 (trust_score / private_skills)。
    """

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    supported_interfaces: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    trust_score: float = 0.0
    private_skills: list[str] = field(default_factory=list)
    owner_user_id: Optional[str] = None  # per D66=B RBAC


# ────────────────────────────────────────────────────────
# Health check (health_check output)
# ────────────────────────────────────────────────────────

@dataclass
class HealthCheckResult:
    """Health check result (per design doc §二.2.3 tool 1)."""

    status: str = "ok"           # "ok" | "degraded" | "unreachable"
    version: Optional[str] = None
    uptime_seconds: int = 0


# ────────────────────────────────────────────────────────
# List tasks (list_tasks output)
# ────────────────────────────────────────────────────────

@dataclass
class ListTasksFilter:
    """list_tasks 可选过滤参数(per design doc §二.2.3 tool 6)。"""

    status: list[str] = field(default_factory=list)  # 期望 ["completed", "failed"]
    context_id: Optional[str] = None
    limit: int = 50
    offset: int = 0


@dataclass
class ListTasksResult:
    """list_tasks 返回(per design doc §二.2.3 tool 6 result)。"""

    tasks: list[Task] = field(default_factory=list)
    next_offset: Optional[int] = None


# ────────────────────────────────────────────────────────
# Push notification config (create_task_push_notification_config)
# ────────────────────────────────────────────────────────

@dataclass
class PushConfig:
    """Push notification config input (per design doc §二.2.3 tool 9)。"""

    url: str = ""
    events: list[str] = field(default_factory=list)  # e.g. ["task.completed", "task.failed"]
    secret: Optional[str] = None


@dataclass
class PushConfigResult:
    """create_task_push_notification_config 返回。"""

    config_id: Optional[str] = None