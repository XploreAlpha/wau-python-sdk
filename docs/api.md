# API 参考

> ⚠️ **本文档已迁移到 [../API.md](../API.md)(Stage 3.2 SDK doc 完整化,2026-07-02)**
>
> 旧版本(v0.6.0-preview.1 P1 阶段)仅保留作历史参考。
> **请使用最新版本** [../API.md](../API.md),包含:
> - 完整 11 端点 × 6 服务 × 2 同步/异步镜像
> - ChatService(Stage 3.1 #5 Python SDK 2xx 实测,chatcmpl-2a19212e / 13 tokens)
> - Bot 子包(telegram / discord / webhook per D13)
> - 9 sentinel error + 9 handshake sentinel + wau-edge 6 错误码
> - 配套 FAQ:[../FAQ.md](../FAQ.md)(10 通用 + 5 Python 特定)

---

# 历史版本(已迁移,仅作参考)

v0.6.0-preview.1 P1 阶段(11 HTTP 端点)
P2 (gRPC 20 RPC) 推到 M3.1;P3 (A2A/AFP 协议层) 推到 v0.7.0+

## Client

### `wau_sdk.Client(base_url, options=None)`

创建 SDK 同步客户端。

**参数**:
- `base_url` (str): kernel HTTP 地址,例如 `http://localhost:18400`
- `options` (`ClientOptions`, 可选): 0 个或多个 `WithXxx()` 配置

**返回**:
- `Client` (可并发安全,context manager)

**示例**:
```python
import wau_sdk
c = wau_sdk.Client("http://localhost:18400")
```

### `wau_sdk.AsyncClient(base_url, options=None)`

创建 SDK 异步客户端(API 镜像 `Client`,所有方法 `async`)。需 `asyncio`。

### `Client.close()` / `AsyncClient.close()`

释放资源。M3.1 gRPC client 才有实质作用,当前是 no-op。

### `Client.circuit_state()`

返回 SDK 内部熔断状态:`"closed"` / `"open"` / `"half-open"`(debug / metrics 用)。

---

## KernelService

### `KernelService.info() -> KernelInfo`

`GET /kernel/info` — 返回 kernel 元信息(version, startTime, uptime, agentsCount, tasksCount)。

### `KernelService.health() -> HealthResponse`

`GET /health` — 检查 kernel 健康(redis 连通性、版本、uptime)。

---

## AgentsService

### `AgentsService.health() -> HealthResponse`

`GET /health`(同 `KernelService.health`)。

### `AgentsService.list(opts=None) -> AgentListResponse`

`GET /registry/agents?page=...&pageSize=...&skill=...&status=...&search=...`

`PageOptions` 字段:
- `page` (int): 1-based 页码,默认 1
- `pageSize` (int): 默认 10,最大 100
- `skill` (str|None): 可选技能过滤
- `status` (str|None): 可选状态过滤
- `search` (str|None): 可选模糊匹配

### `AgentsService.iter(opts=None) -> Iterator[Agent]`

迭代器,懒加载遍历所有页。

```python
for agent in c.agents.iter(wau_sdk.PageOptions(pageSize=20)):
    print(agent.name, agent.trust, agent.status)
```

### `AgentsService.get(name) -> AgentStatus`

`GET /registry/agents/{name}/status` — 综合状态(load + trust + circuit)。

### `AgentsService.score(name) -> AgentScore`

`GET /registry/agents/{name}/score` — 5 维评分(总分 + trust + skill + health + load)。

### `AgentsService.register(req) -> None`

`POST /registry/agents/register` — 注册新 agent(RBAC: trusted_agent / kernel_core)。

```python
c.agents.register(wau_sdk.AgentRegisterRequest(
    name="my-agent",
    url="http://my-agent:18800",
    description="...",
    skills=["clinical-decision-support"],
    universes=["medical"],
))
```

### `AgentsService.deregister(name) -> None`

`DELETE /registry/agents/{name}` — 注销 agent。

### `AgentsService.heartbeat(agent_id) -> None`

`POST /registry/agents/heartbeat` — agent 主动心跳上报(60s 一次)。

### `AgentsService.report_load(agent_id, load) -> None`

`POST /heartbeat/load` — 上报运行时负载(ActiveTasks / MaxCapacity / CPU / Memory)。

---

## TasksService

### `TasksService.submit(req) -> SubmitResponse`

`POST /registry/tasks/submit` — L4 真发 A2A。

```python
resp = c.tasks.submit(wau_sdk.SubmitRequest(
    prompt="What is the capital of France?",
    timeout_ms=30000,
))
# resp.selected_agent, resp.score, resp.response, resp.a2a_call_ms
```

### `TasksService.simulate(req) -> DecisionInfo`

`POST /registry/tasks/simulate` — L3 决策(不真发)。
返回 `DecisionInfo`(不返 a2a_call_ms / response,因为没真发)。

### `TasksService.get(task_id) -> Task`

`GET /registry/tasks/{task_id}` — 查询任务详情。

---

## IntentService (M3.1 stub)

P2 阶段 stub,所有方法返 `wau_sdk.NotImplementedError`:
- `IntentService.recommend(prompt, top_k=1) -> Any`
- `IntentService.parse_intent(text) -> Any`
- `IntentService.list_agents(online_only=True) -> Any`
- `IntentService.health_check() -> Any`

---

## 类型 / DTO

所有 DTO 在 [`types.py`](../src/wau_sdk/types.py)。字段以 **kernel 真相源**为准(参考 [ADR-0002](https://github.com/XploreAlpha/wau-go-sdk/blob/main/docs/adr/0002-sdk-stage-stratification.md))。

### SubmitRequest(关键修正)

```python
@dataclass
class SubmitRequest:
    prompt: str       # 必填,kernel 端 binding:"required" 校验
    timeout_ms: int | None = None
```

跟 wau-cli 旧 DTO(`{message, sourcePeer, sourceAgentId, intent}`)不同。SDK 以 kernel 真相源为准。

### SubmitResponse

```python
@dataclass
class SubmitResponse:
    task_id: str
    agent_id: str | None
    score: float
    decision: DecisionInfo
    status: str          # "completed" | "failed" | "timeout"
    selected_agent: str | None
    a2a_call_ms: int
    response: Any         # 中英兼容 str / dict
    error: str | None
```

---

## 错误

所有错误继承 `WauError`,可用 `isinstance` 或 `except WauErrorSubclass` 匹配。

| Sentinel | 状态码 | 触发 |
|---|---|---|
| `wau_sdk.NotFoundError` | 404 | 资源不存在 |
| `wau_sdk.UnauthorizedError` | 401 | 鉴权失败 |
| `wau_sdk.ForbiddenError` | 403 | RBAC 不足 |
| `wau_sdk.BadRequestError` | 400 | 字段缺失 / 格式错 |
| `wau_sdk.ConflictError` | 409 | 资源冲突 |
| `wau_sdk.APIError`(基类)| 其他 4xx/5xx | 通用 HTTP 错 |
| `wau_sdk.CircuitOpenError` | — | 熔断开 |
| `wau_sdk.MaxRetriesError` | — | 重试耗尽(wraps last error) |
| `wau_sdk.NotImplementedError` | — | P2 stub |

`APIError` 含 `status_code` / `code` / `message` / `request_id` / `body`,用 `isinstance` + `e.status_code` 处理:

```python
try:
    resp = c.tasks.submit(req)
except wau_sdk.APIError as e:
    logger.error(f"status={e.status_code} request_id={e.request_id} body={e.body!r}")
```
