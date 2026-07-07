"""DTO 定义 — 跟 wau-go-sdk types.go 字段 1:1 对应
所有字段以 WAU-core-kernel 真相源为准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============== Agent Runtime DTO(v1.3.1 M11 P2, 2026-07-07)==============
#
# per v1.0.0 M11 W4-W5 design + D67=B(Sidecar subprocess) + D69=A(agentskills.io 标准):
#   - 字段 snake_case(Pythonic 风格)+ JSON 序列化 camelCase(跟 wau-agent Go RPC 对齐)
#   - RunAgent: 走 wau-agent HTTP JSON-RPC gateway(端口 19408)/rpc
#   - Skill: 走 wau-registry HTTP(端口 18401)/registry/skills/*
#   - RegisterAgent: 走 wau-registry HTTP(端口 18401)/registry/agents(老契约,D60 兼容)


@dataclass
class RunAgentRequest:
    """RunAgent RPC 入参(per wau-agent internal/rpc/server.go RunAgentArgs)

    字段对齐 wau-agent net/rpc Gob(同时 HTTP JSON-RPC gateway 走 JSON 包装):
      user_id, bot_id, prompt, context_id, timeout_sec
    """
    user_id: str
    bot_id: str
    prompt: str
    context_id: str = ""
    timeout_sec: int = 30


@dataclass
class RunAgentResponse:
    """RunAgent RPC 出参(per wau-agent internal/rpc/server.go RunAgentReply)

    字段:
      response       — 智能体回复文本(由 hermes-agent LLM loop 生成)
      context_id     — 会话 ID(新会话 = 服务端生成,后续回传让 hermes 续接)
      provider       — LLM provider 名称(透传 hermes 选择,debug / audit 用)
      tokens_used    — token 用量(prompt + completion)
      elapsed_ms     — 实际耗时(毫秒)
    """
    response: str = ""
    context_id: str = ""
    provider: str = ""
    tokens_used: int = 0
    elapsed_ms: int = 0


@dataclass
class Skill:
    """Skill 注册表条目(per agentskills.io 标准 + wau-registry-skill 计划表)

    字段对齐 agentskills.io v1 manifest spec:
      name, description, version, author, universe,
      parameters(dict), entrypoint(str), source_url
    老字段(user_id, is_builtin)WAU 扩展,C 端 / B 端 0 改。
    """
    name: str
    description: str = ""
    version: str = "0.1.0"
    author: str = ""
    universe: str = "default"
    parameters: dict = field(default_factory=dict)
    entrypoint: str = ""
    source_url: str = ""
    # WAU 扩展
    user_id: str = ""  # C 端用户 ID(B 端为空)
    is_builtin: bool = False  # 内置 skill(weather/reminder/opencalw)


@dataclass
class SkillListResponse:
    """GET /registry/skills 列表响应"""
    skills: list[Skill] = field(default_factory=list)
    total: int = 0


@dataclass
class LoadSkillRequest:
    """POST /registry/skills/load 入参(per D69=A agentskills.io load spec)"""
    user_id: str
    skill_name: str
    bot_id: str = ""
    install: bool = True  # True = install(持久化), False = load(临时)


@dataclass
class LoadSkillResponse:
    """POST /registry/skills/load 出参"""
    skill_name: str
    loaded: bool
    entrypoint: str = ""
    parameters: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class RegisterAgentManifest:
    """RegisterAgentManifest — agent 注册 manifest(per M11 P4 + agentskills.io)

    字段 snake_case(JSON camelCase via field metadata):
      name, description, version, entrypoint,
      skills(list[str]), universes(list[str]),
      parameters(dict), source_url

    调用方:wau-agent daemon / SDK caller POST /registry/agents/register
    """
    name: str
    description: str = ""
    version: str = "0.1.0"
    entrypoint: str = ""
    skills: list[str] = field(default_factory=list)
    universes: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    source_url: str = ""


# ============== Skill Publish DTO(v1.3.1 M11 P4 / I 子项, 2026-07-07)==============


@dataclass
class SkillPublishResponse:
    """Skill Publish 响应(POST /registry/skills/publish)

    字段(per wau-registry skill.go handlerPublishSkill):
      name, version, entrypoint, bundle_size, bundle_sha
    """
    name: str
    version: str
    entrypoint: str
    bundle_size: int = 0
    bundle_sha: str = ""


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
    # universe_labels K8s-style labels(per universe,v0.8.0 M3-2B 新增)
    #   - 业务分组用 universes(原字段,保持向后兼容)
    #   - 资源 / 调度特征用 universe_labels(新字段)
    #   - 老 client 不传 → 空 dict(server 视为空)
    #   - 字段名跟 afp-protocol v0.2 + WAU-core-kernel proto + wau-go-sdk 1:1 对齐
    universe_labels: dict[str, str] = field(default_factory=dict)
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
    # universe_labels 跟 Agent.universe_labels 字段语义一致(v0.8.0 M3-2B 新增)
    universe_labels: dict[str, str] = field(default_factory=dict)


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


# v0.8.0 M5-1 B.1 — Handshake DTO
# 字段 1:1 对齐 kernel internal/handshake/session.go:92-142


@dataclass
class HandshakeRequest:
    """POST /v0.8.0/handshake/sessions 请求体

    必填: tenant_id, agent_id(client_id 不填时自动用 SDK user_agent)
    可选: protocol(默认 "a2a"), universe
    """
    tenant_id: str
    client_id: str = ""
    agent_id: str = ""
    protocol: str = "a2a"
    universe: str = ""


@dataclass
class HandshakeResponse:
    """POST /v0.8.0/handshake/sessions 响应(6 字段)

    复用判断: reused=True 表示 kernel 命中已存在 session。
    """
    session_id: str
    direct_endpoint: str
    protocol: str
    expires_at: str  # RFC3339
    ttl_seconds: int
    reused: bool


@dataclass
class HandshakeSessionDetail:
    """GET /v0.8.0/handshake/sessions/{id} 响应(11 字段)"""
    session_id: str
    tenant_id: str
    client_id: str
    agent_id: str
    direct_endpoint: str
    protocol: str
    trust_score: float = 0.0
    created_at: str = ""
    expires_at: str = ""
    ttl_seconds: int = 0
    reuse_count: int = 0


@dataclass
class HandshakeStats:
    """GET /admin/handshake/stats 响应"""
    total_sessions: int = 0
    total_reuses: int = 0
    reuse_hit_rate: float = 0.0
    active_sessions: int = 0
    per_tenant: dict = field(default_factory=dict)


# ============== Chat / LLM DTO(v0.9.0 M3 §3.7 新增,per D20 architecture-pivot)==============
# 字段 1:1 对齐 OpenAI Chat Completions API + wau-go-sdk Chat DTO,
# 4 SDK 通用,test mock 跟真 wau-edge 字节级兼容(per M2 §2.5 端到端 mock 验证)。


@dataclass
class ChatMessage:
    """One message in a chat conversation (OpenAI compat)."""
    role: str
    content: str
    name: str = ""


@dataclass
class ChatCompletionRequest:
    """OpenAI 兼容的 chat request。

    Model: 必填(如 "gpt-4o-mini" / "claude-haiku"),空时 wau-edge 走 default_model。
    Messages: 必填 ≥ 1 条 user 消息。
    Stream: 雏形期只支持 false(M3 §3.7 续支持 streaming)。
    Universe: 业务分组(透传到 wau-llm-router + new-api),非必填,默认 "default"。
    """
    model: str
    messages: list = field(default_factory=list)  # list[ChatMessage]
    stream: bool = False
    universe: str = ""
    metadata: dict = field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int = 0


@dataclass
class ChatChoice:
    """OpenAI 兼容 choice(per wau-go-sdk)"""
    index: int = 0
    message: ChatMessage = field(default_factory=lambda: ChatMessage(role="", content=""))
    finish_reason: str = ""


@dataclass
class ChatUsage:
    """OpenAI 兼容 token usage"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionResponse:
    """OpenAI 兼容 chat response。

    字段 1:1 对齐 wau-go-sdk ChatCompletionResponse;wau-edge 串联 wau-llm-router / new-api
    后字节级兼容(per M2 §2.5)。
    """
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list = field(default_factory=list)  # list[ChatChoice]
    usage: ChatUsage = field(default_factory=ChatUsage)
    reason: str = ""  # WAU 扩展,wau-llm-router 决策原因
    # WAU 扩展 (Stage 3.1 #11, 2026-07-03) — provider 是 wau-llm-router Resolve 选中的
    # LLM provider 名称(如 "deepseek-v4-flash" / "gpt-4o-mini" / "claude-haiku-4-5"),
    # 透传自 wau-store 真相源,debug / audit / 成本归因用。
    # 老调用方不读 → 无影响(空串兜底,OpenAI spec 不识别 → wau-edge 透传到 router)。
    provider: str = ""


# ============== Streaming SSE DTO(per Stage 3.1 #10, 2026-07-02)==============
#
# OpenAI ChatCompletionChunk 协议 1:1 对齐(per https://platform.openai.com/docs/api-reference/chat-streaming)。
# 4 SDK 通用字段(per Stage 0 4 SDK 5/5 字段对齐)。
#
# 完整链路(per Stage 3.1 #10):
#   SDK → wau-edge :18402 /v1/chat/completions?stream=true
#       → wau-llm-router :18404 Resolve(unary, 拿 userToken + model)
#       → new-api sidecar :3000 /v1/chat/completions?stream=true
#       → DeepSeek v4-flash reasoning model → SSE chunks → 响应回 SDK


@dataclass
class ChunkDelta:
    """OpenAI ChatCompletionChunk.choices[].delta 对象。

    - role 只在首 chunk 有值("assistant"),空串时 omit
    - content 是增量字符流(wau-edge 7 chunks 验证 per C.1:"1" → "+" → "1" → "=" → "2")
    """
    role: str = ""
    content: str = ""


@dataclass
class ChunkChoice:
    """OpenAI ChatCompletionChunk.choices[] 元素。

    finish_reason 字段在流中间为 None(per OpenAI 协议),结束 chunk 为 "stop" / "length"。
    用 Optional[str] + 序列化时 None 转 None,严格对齐 OpenAI spec。
    """
    index: int = 0
    delta: ChunkDelta = field(default_factory=ChunkDelta)
    finish_reason: str | None = None


@dataclass
class ChatCompletionChunk:
    """OpenAI ChatCompletion streaming 响应的一个 chunk(per wau-edge stream.go)。

    wau-edge handler.go handleStream (L204-273) 编码这种格式,SSE 包装为:
      data: {<JSON>}\\n\\n
    终止:data: [DONE]\\n\\n(per stream.go WriteDone)
    """
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list = field(default_factory=list)  # list[ChunkChoice]
