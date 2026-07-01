# wau-python-sdk API 参考

> **版本**:v1.1.0(v0.9.0 "Acorn" Stage 3.2 完整化,2026-07-02)
> **包名**:`wau_sdk`(PyPI)
> **API 数量**:11 HTTP 端点 × 6 服务(Agents / Tasks / Kernel / Intent / Handshake / Chat)+ Bot 子包(per D13)
> **同步/异步双 API**:`Client` 同步 + `AsyncClient` 异步,字段 1:1 对齐 wau-go-sdk(per Stage 0 5/5 字段对齐)
> **配套教程**:`docs/quickstart.md` 5 分钟入门,`docs/auth.md` HS256 鉴权,`docs/retry_circuit.md` 重试/熔断

---

## 目录

1. [安装](#1-安装)
2. [Client 初始化](#2-client-初始化)
3. [核心 API](#3-核心-api)
   - [3.1 Auth — Signer / AuthConfig / Role](#31-auth--signer--authconfig--role)
   - [3.2 KernelService](#32-kernelservice)
   - [3.3 AgentsService](#33-agentsservice)
   - [3.4 TasksService](#34-tasksservice)
   - [3.5 HandshakeService](#35-handshakeservice)
   - [3.6 IntentService(M3.1 stub)](#36-intentservice-m31-stub)
   - [3.7 ChatService ⭐(Stage 3.1 2xx 验证)](#37-chatservice-stage-3-1-2xx-验证)
   - [3.8 Retry / Circuit 状态查询](#38-retry--circuit-状态查询)
4. [Bot 子包(per D13)](#4-bot-子包per-d13)
5. [配置项](#5-配置项)
6. [类型定义](#6-类型定义)
7. [错误码](#7-错误码)
8. [版本与变更](#8-版本与变更)

---

## 1. 安装

```bash
# 1.1 标准 pip install(从 PyPI)
pip install wau-sdk==1.1.0

# 1.2 pyproject.toml 锁版本
[project.dependencies]
wau-sdk = "1.1.0"

# 1.3 依赖(自动拉取,per pyproject.toml)
#   - httpx>=0.27        (HTTP 客户端)
#   - PyJWT>=2.8         (HS256 鉴权)
#   - tenacity>=8.2      (重试指数退避 + 抖动)
#   - grpclib>=0.4       (M3.1 gRPC stub)
#   - protobuf>=5.27     (M3.1 gRPC stub)
```

**前置依赖**:
- Python ≥ 3.10(用了 `dataclass(slots=True)` / `match` / `int | None`)
- 目标 WAU 服务:wau-core-kernel(默认 `:18400`)+ wau-edge(默认 `:18402` Chat)

---

## 2. Client 初始化

### 2.1 `wau_sdk.Client(base_url, options=None)` / `wau_sdk.AsyncClient(base_url, options=None)`

**创建 SDK 客户端**(同步 / 异步双版本,镜像 API)。

| 参数 | 类型 | 说明 |
|---|---|---|
| `base_url` | `str` | wau-core-kernel HTTP 地址,例如 `http://localhost:18400` |
| `options` | `ClientOptions \| None` | 配置对象,默认 `ClientOptions()` |

**返回**:
- `Client` / `AsyncClient`(context manager:同步 `with` / 异步 `async with`)

**示例 — 同步**:
```python
import os
import wau_sdk

# 最简用法(无需鉴权,只能调公开端点)
with wau_sdk.Client("http://localhost:18400") as c:
    info = c.kernel.info()
    print(f"kernel {info.version} uptime={info.uptime}s")

# 完整配置(timeout + retry + circuit + auth)
options = wau_sdk.ClientOptions(
    timeout_ms=30_000,
    retry=wau_sdk.RetryConfig(max_retries=3),
    circuit=wau_sdk.CircuitConfig(failure_threshold=5),
    auth=wau_sdk.AuthConfig(
        role=wau_sdk.Role.EXTERNAL_AGENT,
        agent_name="my-agent",
        tenant_id="tenant-A",  # ⭐ 必填(per Stage 3.1 #1 修复)
        shared_secret=os.environ["WAU_EDGE_JWT_SECRET"].encode(),
    ),
)
with wau_sdk.Client("http://localhost:18400", options) as c:
    print(f"base_url={c.base_url}, circuit={c.circuit_state()}")
```

**示例 — 异步**:
```python
import asyncio
import wau_sdk

async def main():
    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        agents = await c.agents.list()
        for a in agents.agents:
            print(a.name, a.trust, a.status)

asyncio.run(main())
```

### 2.2 顶层 `ClientOptions` 字段

| 字段 | 类型 | 默认 | 用途 |
|---|---|---|---|
| `timeout_ms` | `int` | `30000` | 单次请求超时(ms) |
| `retry` | `RetryConfig` | `RetryConfig()` | 重试策略(指数退避 + 抖动) |
| `circuit` | `CircuitConfig` | `CircuitConfig()` | 熔断策略 |
| `auth` | `AuthConfig \| None` | `None` | HS256 JWT 鉴权(per Stage 3.1 #1) |
| `user_agent` | `str` | `"wau-python-sdk/0.6.0-preview.1"` | HTTP UA 头 |
| `transport` | `Any` | `None` | httpx.Client / AsyncClient 注入点(测试 / 代理) |

### 2.3 助手函数

| 函数 | 说明 |
|---|---|
| `default_options()` | 返 `ClientOptions()` 默认配置(Quickstart 用) |
| `with_timeout(options, ms)` | 修改 `options.timeout_ms = ms`,返 `options`(链式) |
| `with_retry_no(options)` | 修改 `options.retry.max_retries = 0`,禁用重试 |
| `with_circuit_disabled(options)` | 修改 `options.circuit.enabled = False`,禁用熔断 |
| `with_auth(options, auth)` | 设置 `options.auth = auth`,返 `options`(链式) |

```python
import wau_sdk
opts = wau_sdk.default_options()
opts = wau_sdk.with_timeout(opts, 60_000)
opts = wau_sdk.with_auth(opts, wau_sdk.AuthConfig(
    agent_name="my-agent",
    tenant_id="tenant-A",
    shared_secret=b"supersecret",
))
c = wau_sdk.Client("http://localhost:18400", opts)
```

### 2.4 `Client.base_url` / `Client.options` / `Client.circuit_state()` / `Client.close()`

| 属性 / 方法 | 类型 | 说明 |
|---|---|---|
| `base_url` | `str` | 返回 base URL(debug / metrics 用) |
| `options` | `ClientOptions` | 返回当前配置对象(只读语义) |
| `circuit_state()` | `str` | 返 SDK 内部熔断状态:`"closed"` / `"open"` / `"half-open"` |
| `close()` | `None` / `Awaitable[None]` | 释放资源(同步调 / 异步 `await`),M3.1 gRPC client 才需要,当前 no-op |

上下文管理器自动 `close`:
```python
# 同步
with wau_sdk.Client(...) as c:
    ...

# 异步
async with wau_sdk.AsyncClient(...) as c:
    ...
```

---

## 3. 核心 API

### 3.1 Auth — Signer / AuthConfig / Role

> **Stage 3.1 #1 修复(2026-07-01)**:wau-edge `Claims` 必填 `tenant_id`(per
> `wau-edge/internal/auth/jwt.go:96-98`)。SDK 必须签 `tenant_id`,否则 401。
> Subject 对齐 wau-edge Claims.Subject(`sub` claim),空时用 `agent_name` 兜底。

#### 3.1.1 `Role` enum

| 值 | 字面量 | 用途 |
|---|---|---|
| `Role.KERNEL_CORE` | `"kernel_core"` | kernel 进程本身 |
| `Role.TRUSTED_AGENT` | `"trusted_agent"` | 注册过的可信 agent(可注册/注销) |
| `Role.EXTERNAL_AGENT` | `"external_agent"` | 外部 agent(可调 chat/查询) |

```python
import wau_sdk
role = wau_sdk.Role.TRUSTED_AGENT
print(role.value)  # "trusted_agent"
```

#### 3.1.2 `AuthConfig` dataclass

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `role` | `Role` | 否(默认 `EXTERNAL_AGENT`) | RBAC 角色 |
| `agent_name` | `str` | **是** | Agent 名称(JWT `agent` claim) |
| `tenant_id` | `str` | **是**(非空字符串) | 租户 ID(JWT `tenant_id` claim,wau-edge 必校验) |
| `subject` | `str` | 否(空 = 用 `agent_name` 兜底) | JWT `sub` claim(用户/Agent 标识) |
| `shared_secret` | `bytes` | **是** | HS256 共享密钥(从 env 或安全存储读取) |

**校验**:`__post_init__` 强制检查 `shared_secret` / `agent_name` / `tenant_id` 非空,空时 raise `ValueError`。

```python
import os
import wau_sdk

auth = wau_sdk.AuthConfig(
    role=wau_sdk.Role.TRUSTED_AGENT,
    agent_name="my-agent",
    tenant_id="tenant-A",  # ⭐ 必填
    subject="user-123",    # 可选,空时用 agent_name 兜底
    shared_secret=os.environ["WAU_EDGE_JWT_SECRET"].encode(),
)
```

#### 3.1.3 `Signer.sign(ttl_seconds=300) -> str`

**HS256 JWT 签发器**(`AuthConfig` 不可变 = 启动时构造一次,每次请求 `sign()` 一次)。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `ttl_seconds` | `int` | `300` | JWT 过期秒数(5 min) |

**返回**:`str` — 编码后的 JWT 字符串。

**JWT Payload 7 字段**(per Stage 3.1 #1 修复):

```json
{
  "agent":     "my-agent",
  "role":      "trusted_agent",
  "sub":       "user-123",
  "tenant_id": "tenant-A",   // ⭐ 必填(wau-edge 校验)
  "iat":       1718342400,
  "exp":       1718342700,  // iat + 300s
  "jti":       "uuid-v4"    // 防重放
}
```

```python
import wau_sdk

# 构造 Signer(失败时 raise ValueError)
signer = wau_sdk._auth.Signer(auth)
print(signer.role)  # "trusted_agent"

# 签 JWT(每次请求新签,5min 默认有效)
token = signer.sign(ttl_seconds=300)
print(token[:50])  # "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**校验链**(server 端):
- wau-edge `Claims` 校验 `tenant_id` 非空(per `wau-edge/internal/auth/jwt.go:96-98`)
- 缺 `tenant_id` → 401 `{"error":"tenant_id missing"}`(per [[project-v0-9-0-blocker-fix-1-plus-2-2026-07-01]])
- wau-edge 默认空 secret = 严格 reject,**必须 env `WAU_EDGE_JWT_SECRET=xxx` 启动 wau-edge**

#### 3.1.4 完整 Auth 示例

```python
import os
import wau_sdk

auth = wau_sdk.AuthConfig(
    role=wau_sdk.Role.TRUSTED_AGENT,
    agent_name="my-agent",
    tenant_id="tenant-A",                # ⭐ 必填
    subject="user-123",                  # 可选
    shared_secret=os.environ["WAU_EDGE_JWT_SECRET"].encode(),
)

opts = wau_sdk.ClientOptions(
    timeout_ms=30_000,
    auth=auth,
)

with wau_sdk.Client("http://localhost:18402", opts) as c:  # 注意:wau-edge 端口
    resp = c.chat.completions(wau_sdk.ChatCompletionRequest(
        model="wau-default",
        messages=[wau_sdk.ChatMessage(role="user", content="hello")],
    ))
    print(f"chatcmpl:{resp.id} tokens={resp.usage.total_tokens}")
```

---

### 3.2 KernelService

#### 3.2.1 `KernelService.info() -> KernelInfo`

`GET /kernel/info` — 返 kernel 元信息(`version`, `startTime`, `uptime`, `agentsCount`, `tasksCount`)。

```python
with wau_sdk.Client("http://localhost:18400") as c:
    info = c.kernel.info()
    print(f"kernel {info.version} uptime={info.uptime}s agents={info.agentsCount}")
```

#### 3.2.2 `KernelService.health() -> HealthResponse`

`GET /health` — 检查 kernel 健康(redis 连通性、版本、uptime、错误码)。

```python
with wau_sdk.Client("http://localhost:18400") as c:
    h = c.kernel.health()
    if h.status == "ok" and h.redis == "connected":
        print("✅ kernel healthy")
    else:
        print(f"❌ kernel error={h.error}")
```

**异步版本**:`c.kernel_async.health()` / 走 `async with AsyncClient` 模式。

---

### 3.3 AgentsService

#### 3.3.1 `AgentsService.list(opts=None) -> AgentListResponse`

`GET /registry/agents?page=...&pageSize=...&skill=...&status=...&search=...`

`PageOptions` 字段(`dataclass`):

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page` | `int` | `1` | 1-based 页码 |
| `pageSize` | `int` | `10` | 页面大小(最大 100) |
| `skill` | `str \| None` | `None` | 可选技能过滤 |
| `status` | `str \| None` | `None` | 可选状态过滤 |
| `search` | `str \| None` | `None` | 可选模糊匹配 |

```python
opts = wau_sdk.PageOptions(page=1, pageSize=20, skill="clinical-decision-support")
with wau_sdk.Client("http://localhost:18400") as c:
    resp = c.agents.list(opts)
    print(f"total={resp.total} page={resp.page}/{resp.totalPages}")
    for a in resp.agents:
        print(f"  {a.name}: trust={a.trust} universes={a.universes}")
```

#### 3.3.2 `AgentsService.iter(opts=None) -> Iterator[Agent]`

迭代器,懒加载遍历所有页(Python 风格 for-loop):

```python
with wau_sdk.Client("http://localhost:18400") as c:
    for agent in c.agents.iter(wau_sdk.PageOptions(pageSize=50)):
        print(agent.name, agent.trust, agent.status)
```

#### 3.3.3 `AgentsService.get(name) -> AgentStatus`

`GET /registry/agents/{name}/status` — 综合状态(load + trust + circuit)。

#### 3.3.4 `AgentsService.score(name) -> AgentScore`

`GET /registry/agents/{name}/score` — 5 维评分(`totalScore` + `trustScore` + `skillMatch` + `healthScore` + `loadScore`)。

#### 3.3.5 `AgentsService.register(req) -> None`

`POST /registry/agents/register` — 注册新 agent(RBAC: `trusted_agent` / `kernel_core`)。

```python
with wau_sdk.Client("http://localhost:18400", auth_opts) as c:
    c.agents.register(wau_sdk.AgentRegisterRequest(
        name="my-agent",
        url="http://my-agent:18800",
        description="Medical CDS agent",
        skills=["clinical-decision-support"],
        universes=["medical"],
        universe_labels={"region": "us-east", "gpu": "a100"},  # v0.8.0 M3-2B K8s labels
    ))
```

#### 3.3.6 `AgentsService.deregister(name) -> None`

`DELETE /registry/agents/{name}` — 注销 agent。

#### 3.3.7 `AgentsService.heartbeat(agent_id) -> None`

`POST /registry/agents/heartbeat` — agent 主动心跳上报(60s 一次)。

#### 3.3.8 `AgentsService.report_load(agent_id, load) -> None`

`POST /heartbeat/load` — 上报运行时负载(`activeTasks` / `maxCapacity` / `cpuUsage` / `memoryUsage`)。

```python
load = wau_sdk.AgentLoad(
    activeTasks=3,
    maxCapacity=10,
    cpuUsage=0.45,
    memoryUsage=0.62,
)
c.agents.report_load("my-agent", load)
```

---

### 3.4 TasksService

#### 3.4.1 `TasksService.submit(req) -> SubmitResponse`

`POST /registry/tasks/submit` — L4 真发 A2A。

```python
with wau_sdk.Client("http://localhost:18400") as c:
    resp = c.tasks.submit(wau_sdk.SubmitRequest(
        prompt="What is the capital of France?",
        timeout_ms=30000,
    ))
    print(f"✅ {resp.selected_agent}: score={resp.score:.2f} "
          f"a2a={resp.a2a_call_ms}ms response={resp.response}")
```

**`SubmitRequest` 关键修正**(per Stage 0):
- 只有 2 个字段:`prompt`(必填)+ `timeout_ms`(可选)
- wau-cli 旧 DTO(`{message, sourcePeer, ...}`)已废弃
- SDK 以 kernel 真相源为准(per [[project-v0-9-0-stage0-closure-2026-06-28]])

#### 3.4.2 `TasksService.simulate(req) -> DecisionInfo`

`POST /registry/tasks/submit/simulate`(L3 决策) — 走 Thompson 评分但不真发。
返 `DecisionInfo`(无 `a2a_call_ms` / `response`)。

#### 3.4.3 `TasksService.get(task_id) -> Task`

`GET /registry/tasks/{task_id}` — 查询任务详情(`status` / `assignedAgent` / `result`)。

---

### 3.5 HandshakeService

> **v0.8.0 M5-1 B.1**:4 SDK Handshake Client 当日完成,字段 1:1 对齐 `kernel/internal/handshake/session.go:92-142`。

#### 3.5.1 `HandshakeService.create_session(req) -> HandshakeResponse`

`POST /v0.8.0/handshake/sessions` — 创建 handshake session(返回 `direct_endpoint`,4 SDK 复用同一逻辑)。

```python
req = wau_sdk.HandshakeRequest(
    tenant_id="tenant-A",     # 必填
    client_id="my-bot-v1",    # 可选(空时自动用 SDK user_agent)
    agent_id="my-agent",
    protocol="a2a",
    universe="medical",
)
with wau_sdk.Client("http://localhost:18400", auth_opts) as c:
    resp = c.handshake.create_session(req)
    print(f"session_id={resp.session_id} direct={resp.direct_endpoint} reused={resp.reused}")
```

#### 3.5.2 `HandshakeService.get_session(session_id) -> HandshakeSessionDetail`

`GET /v0.8.0/handshake/sessions/{id}` — 查询 session 详情(11 字段)。

#### 3.5.3 `HandshakeService.get_stats() -> HandshakeStats`

`GET /admin/handshake/stats` — 全局统计(`total_sessions` / `total_reuses` / `reuse_hit_rate` / `per_tenant`)。

---

### 3.6 IntentService(M3.1 stub)

P2 / M3.1 阶段 stub,所有方法返 `wau_sdk.NotImplementedError`:
- `IntentService.recommend(prompt, top_k=1) -> Any`
- `IntentService.parse_intent(text) -> Any`
- `IntentService.list_agents(online_only=True) -> Any`
- `IntentService.health_check() -> Any`

```python
import wau_sdk
with wau_sdk.Client("http://localhost:18400") as c:
    try:
        c.intent.recommend("hi")
    except wau_sdk.NotImplementedError as e:
        print(f"⏳ IntentService M3.1 阶段未实装: {e}")
```

---

### 3.7 ChatService ⭐(Stage 3.1 2xx 验证)

> **v0.9.0 M3 §3.7 + D20 architecture-pivot**:Chat 直连 wau-edge `:18402/v1/chat/completions`(走 wau-llm-router + new-api),替换 v0.8.0 时代 `Tasks().Submit` 旧路径。
> **Stage 3.1 #5 Python SDK e2e(2026-07-01)**:真实 2xx 响应 = `chatcmpl-2a19212e` / `wau-default` / 1 choice / **13 tokens** ✅。

#### 3.7.1 `ChatService.completions(req) -> ChatCompletionResponse` / 异步版

`POST /v1/chat/completions`(OpenAI 兼容)。

**完整链路**(per M3 §4.5.1):
```
bot → wau-edge :18402 /v1/chat/completions
     → wau-llm-router :18404 /v1/resolve  (决定 userToken + model)
     → new-api :3000 /v1/chat/completions  → LLM provider
```

**同步示例**(实测 2xx):
```python
import wau_sdk

with wau_sdk.Client("http://localhost:18402", auth_opts) as c:  # wau-edge 端口
    resp = c.chat.completions(wau_sdk.ChatCompletionRequest(
        model="wau-default",
        messages=[
            wau_sdk.ChatMessage(role="user", content="Say hi in 3 words"),
        ],
    ))
    print(f"chatcmpl:{resp.id} model={resp.model} choices={len(resp.choices)}")
    print(f"usage: prompt={resp.usage.prompt_tokens} "
          f"completion={resp.usage.completion_tokens} "
          f"total={resp.usage.total_tokens} tokens")
    print(f"answer: {resp.choices[0].message.content}")
# 输出:
# chatcmpl:chatcmpl-2a19212e model=wau-default choices=1
# usage: prompt=12 completion=1 total=13 tokens
# answer: Hello there friend!
```

**异步示例**:
```python
import asyncio
import wau_sdk

async def main():
    async with wau_sdk.AsyncClient("http://localhost:18402", auth_opts) as c:
        resp = await c.chat.completions(wau_sdk.ChatCompletionRequest(
            model="wau-default",
            messages=[wau_sdk.ChatMessage(role="user", content="hi")],
        ))
        print(f"chatcmpl:{resp.id} tokens={resp.usage.total_tokens}")

asyncio.run(main())
```

**`ChatCompletionRequest` 字段**:

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `model` | `str` | **是** | — | 模型名(如 `"wau-default"` / `"gpt-4o-mini"` / `"claude-haiku"`),空时 wau-edge 走 default_model |
| `messages` | `list[ChatMessage]` | **是** | `[]` | ≥ 1 条 user 消息 |
| `stream` | `bool` | 否 | `False` | 雏形期只支持 `False` |
| `universe` | `str` | 否 | `""` | 业务分组(透传到 wau-llm-router + new-api) |
| `metadata` | `dict` | 否 | `{}` | 自定义元数据 |
| `temperature` | `float \| None` | 否 | `None` | 0-2 |
| `max_tokens` | `int` | 否 | `0` | 限制最大输出(0 = 不限制) |

**校验**(客户端):
- `model` 为空 → 客户端 `ValueError`(拦在 SDK,不发请求)
- `messages` 为空 → 客户端 `ValueError`

**`ChatCompletionResponse` 字段**(8 字段,1:1 对齐 OpenAI):

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 形如 `chatcmpl-2a19212e`(wau-edge 生成) |
| `object` | `str` | 总是 `"chat.completion"` |
| `created` | `int` | UNIX timestamp(秒) |
| `model` | `str` | 实际用到的模型(可能 = 请求 model 或 wau-edge 重写) |
| `choices` | `list[ChatChoice]` | LLM 返回的 choices(实测 1) |
| `usage` | `ChatUsage` | Token usage(`prompt_tokens` / `completion_tokens` / `total_tokens`) |
| `reason` | `str` | WAU 扩展:wau-llm-router 决策原因 |

#### 3.7.2 Streaming 限制(per Stage 1)

```python
# v0.9.0 alpha:Stream 必须 False
req = wau_sdk.ChatCompletionRequest(
    model="wau-default",
    messages=[wau_sdk.ChatMessage(role="user", content="hi")],
    stream=False,  # ← 必须 False
)
# v1.2.0+:用 StreamingCompletions() (per §8.3 路线)
```

---

### 3.8 Retry / Circuit 状态查询

#### 3.8.1 `RetryConfig` dataclass

| 字段 | 类型 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| `max_retries` | `int` | `3` | ≥ 0 | 最大重试次数(`0` = 不重试) |
| `initial_backoff_ms` | `int` | `200` | > 0 | 初始退避(ms) |
| `max_backoff_ms` | `int` | `5000` | ≥ initial | 最大退避(ms) |
| `jitter` | `float` | `0.2` | [0.0, 1.0] | 抖动比例 |
| `retry_on` | `list[int]` | `[500, 502, 503, 504, 429]` | HTTP 状态码 | 触发重试的状态码 |

**策略**:指数退避 + 抖动。**只对幂等请求自动重试**(GET / HEAD);非幂等 POST 默认不重试。

#### 3.8.2 `CircuitConfig` dataclass

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `failure_threshold` | `int` | `5` | 连续失败次数触发开路 |
| `open_timeout_ms` | `int` | `30000` | 开路持续时间(30s 后半开恢复) |
| `half_open_max` | `int` | `1` | 半开状态允许的探测请求数 |
| `enabled` | `bool` | `True` | 是否启用熔断(测试时可设 `False`) |

#### 3.8.3 `Client.circuit_state() -> str`

```python
with wau_sdk.Client("http://localhost:18400") as c:
    state = c.circuit_state()  # "closed" / "open" / "half-open"
    print(f"circuit={state}")
```

**详细**:`docs/retry_circuit.md`

---

## 4. Bot 子包(per D13)

> **D13 拍板(2026-06-26)**:4 SDK Bot interface 完全统一 — 5 个方法签名 100% 一致。
> Go `Start/Stop/OnMessage/WithTenant/WithUniverse` ↔ Python `start/stop/on_message/with_tenant/with_universe`(全 `async`)。

### 4.1 公共类型(`wau_sdk.bot.common`)

| 类型 | 字段 | 说明 |
|---|---|---|
| `IncomingMessage` | `id` / `text` / `from_id` / `from_name` / `chat_id` / `timestamp` / `attachment` | 收到用户消息 |
| `OutgoingMessage` | `text` / `reply_to` / `attachment` | 发送给用户消息 |
| `Attachment` | `type` / `url` / `mime_type` / `size` | 通用附件(type ∈ `"image"` / `"file"` / `"audio"` / `"video"`) |
| `Bot` | ABC | 抽象基类(强制 5 个 abstract 方法) |
| `BotBuilder` | — | builder 模式构造 Bot(`new_builder()` 创建) |

**4 SDK 必须实现的 5 个方法**(`async` 统一):
1. `async start(self) -> None` — 启动 bot(长连接 / webhook server)
2. `async stop(self) -> None` — 优雅停止
3. `on_message(self, handler) -> Bot` — 注册 handler(签名:`Callable[[IncomingMessage], OutgoingMessage]`)
4. `with_tenant(self, tenant_id) -> Bot` — 设置 tenant 上下文
5. `with_universe(self, universe) -> Bot` — 设置 universe 上下文

### 4.2 Telegram Bot(`wau_sdk.bot.telegram`)— Stage 1 M1 实装

```python
import os
import asyncio
from wau_sdk.bot.telegram import Bot

async def main():
    bot = Bot(
        token=os.environ["TELEGRAM_BOT_TOKEN"],
        tenant_id="tenant-A",
    )

    @bot.on_message
    async def handle(msg):
        # 同步签名也行(per D13 doc string 是 sync 但兼容 async)
        return {"text": f"echo: {msg.text}"}

    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
```

### 4.3 Discord Bot(`wau_sdk.bot.discord`)— Stage 1 M1 实装

```python
import os
import asyncio
from wau_sdk.bot.discord import Bot

async def main():
    bot = Bot(token=os.environ["DISCORD_BOT_TOKEN"], tenant_id="tenant-A")

    @bot.on_message
    async def handle(msg):
        return {"text": f"echo: {msg.text}"}

    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
```

### 4.4 Webhook Bot(`wau_sdk.bot.webhook`)— 通用 HTTP webhook

```python
import os
from wau_sdk.bot.webhook import Bot

bot = Bot(
    listen_addr=":8080",
    path="/webhook",
    tenant_id="tenant-A",
)

@bot.on_message
def handle(msg):
    return {"text": f"echo: {msg.text}"}

bot.start()  # blocking
```

### 4.5 5+ 其他平台(推 v1.0.0)

- **Slack** / **WhatsApp** / **钉钉** / **飞书** / **Email** — 留 v1.0.0 推
- **Stage 3.2** 注册接口已就位(`with_tenant` / `with_universe` 已支持多租户 / 多 universe)
- 跟踪 issue:https://github.com/XploreAlpha/wau-python-sdk/issues

---

## 5. 配置项

### 5.1 环境变量覆盖

| 变量 | 默认 | 用途 |
|---|---|---|
| `WAU_EDGE_JWT_SECRET` | (无) | HS256 共享密钥(从 SDK 注入到 `AuthConfig.shared_secret`) |
| `WAU_KERNEL_BASE_URL` | `http://localhost:18400` | wau-core-kernel 地址(Quickstart 用) |
| `WAU_EDGE_BASE_URL` | `http://localhost:18402` | wau-edge 地址(Chat 用) |
| `WAU_TENANT_ID` | (无) | 当前请求 tenant_id(从 env 读) |

### 5.2 YAML 配置(可选,留 v1.0.0)

```yaml
# ~/.wau/config.yaml(规划,v1.0.0 实装)
default:
  base_url: http://localhost:18400
  timeout_ms: 30000
  retry:
    max_retries: 3
  circuit:
    failure_threshold: 5
  auth:
    role: trusted_agent
    agent_name: my-agent
    tenant_id: tenant-A
```

---

## 6. 类型定义

> 所有 DTO 在 [`src/wau_sdk/types.py`](./src/wau_sdk/types.py)。字段以 **WAU-core-kernel 真相源**为准(per [[project-v0-9-0-stage0-closure-2026-06-28]])。

### 6.1 Chat DTO(per §3.7)

| 类型 | 字段 |
|---|---|
| `ChatMessage` | `role` / `content` / `name=""` |
| `ChatCompletionRequest` | `model` / `messages` / `stream=False` / `universe=""` / `metadata={}` / `temperature=None` / `max_tokens=0` |
| `ChatChoice` | `index=0` / `message` / `finish_reason=""` |
| `ChatUsage` | `prompt_tokens=0` / `completion_tokens=0` / `total_tokens=0` |
| `ChatCompletionResponse` | `id=""` / `object="chat.completion"` / `created=0` / `model=""` / `choices=[]` / `usage` / `reason=""` |

### 6.2 Tasks DTO

```python
@dataclass
class SubmitRequest:
    prompt: str           # 必填
    timeout_ms: int | None = None

@dataclass
class SubmitResponse:
    task_id: str = ""
    agent_id: str | None = None
    agent_url: str | None = None
    score: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    decision: DecisionInfo = field(default_factory=DecisionInfo)
    status: str = ""           # "completed" | "failed" | "timeout"
    selected_agent: str | None = None
    a2a_call_ms: int = 0
    response: Any = None       # 中英兼容 str / dict
    error: str | None = None
    source_peer: str | None = None
    source_agent_id: str | None = None
```

### 6.3 Handshake DTO(v0.8.0 M5-1 B.1)

| 类型 | 字段 |
|---|---|
| `HandshakeRequest` | `tenant_id` / `client_id=""` / `agent_id=""` / `protocol="a2a"` / `universe=""` |
| `HandshakeResponse` | `session_id` / `direct_endpoint` / `protocol` / `expires_at` / `ttl_seconds` / `reused` |
| `HandshakeSessionDetail` | `session_id` / `tenant_id` / `client_id` / `agent_id` / `direct_endpoint` / `protocol` / `trust_score` / `created_at` / `expires_at` / `ttl_seconds` / `reuse_count` |
| `HandshakeStats` | `total_sessions` / `total_reuses` / `reuse_hit_rate` / `active_sessions` / `per_tenant` |

### 6.4 Agents DTO

| 类型 | 字段(部分)|
|---|---|
| `Agent` | `name` / `id=""` / `url=""` / `description=""` / `skills=[]` / `universes=[]` / `universe_labels={}`(v0.8.0 M3-2B)/ `trust=0.0` / `status=""` / `lastSeen=""` |
| `AgentRegisterRequest` | `name` / `url` / `description=""` / `skills=[]` / `universes=[]` / `universe_labels={}` |
| `AgentScore` | `name` / `totalScore` / `trustScore` / `skillMatch` / `healthScore` / `loadScore` |
| `AgentLoad` | `activeTasks` / `maxCapacity=10` / `cpuUsage` / `memoryUsage` |
| `AgentStatus` | `name` / `status` / `trust` / `load` / `circuit="closed"` |

### 6.5 通用的 Request / Response 类型

| 类型 | 字段 |
|---|---|
| `HealthResponse` | `status` / `version` / `uptime` / `redis` / `error` |
| `KernelInfo` | `version` / `startTime` / `uptime` / `agentsCount` / `tasksCount` |
| `PageOptions` | `page=1` / `pageSize=10` / `skill=None` / `status=None` / `search=None` |
| `PageResult[T]`(generic) | `items=[]` / `total=0` / `page=1` / `pageSize=10` / `totalPages=1` |
| `Candidate` | `name` / `score=0.0` / `reason=""` |
| `DecisionInfo` | `selected_agent=""` / `score=0.0` / `decision_time_ms=0` / `candidates=[]` |
| `Task` | `taskId` / `message` / `sourcePeer` / `sourceAgentId` / `status` / `assignedAgent` / `result` / `createdAt` / `updatedAt` / `requiredSkills` |
| `IntentDTO` | `type=""` / `requiredSkills=[]` / `urgency=""` / `estimatedComplexity=0` |

---

## 7. 错误码

> 所有错误继承 `WauError`。HTTP 4xx/5xx 由 `Transport._raise_for_status` 自动映射到对应子类。

### 7.1 `APIError` 基类

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `int` | HTTP 状态码(如 404) |
| `code` | `str` | wau 标准错误码(如 `"not_found"`) |
| `message` | `str` | 人类可读消息 |
| `request_id` | `str` | server 端 request ID(用于日志追踪)|
| `body` | `bytes` | 原始响应体(debug 用,前 200 字符自动截断) |

**捕获示例**:
```python
import wau_sdk
try:
    resp = c.tasks.submit(wau_sdk.SubmitRequest(prompt="hi"))
except wau_sdk.APIError as e:
    logger.error(f"status={e.status_code} code={e.code} "
                 f"request_id={e.request_id} body={e.body!r}")
```

### 7.2 9 SDK Sentinel(per Stage 1)

| 异常类 | 状态码 | 触发 |
|---|---|---|
| `wau_sdk.NotFoundError` | 404 | 资源不存在 |
| `wau_sdk.UnauthorizedError` | 401 | 鉴权失败(per Stage 3.1 #1 缺 `tenant_id` 也会触发) |
| `wau_sdk.ForbiddenError` | 403 | RBAC 不足 |
| `wau_sdk.BadRequestError` | 400 | 字段缺失 / 格式错 |
| `wau_sdk.ConflictError` | 409 | 资源冲突(重名注册等) |
| `wau_sdk.APIError` | 其他 4xx/5xx | 通用 HTTP 错(基类) |
| `wau_sdk.CircuitOpenError` | — | 熔断开("circuit breaker is open") |
| `wau_sdk.MaxRetriesError` | — | 重试耗尽(`__cause__` 包 `last_error`) |
| `wau_sdk.NotImplementedError`(自定义)| — | P2 stub(IntentService) |

**捕获约定**:`isinstance` + 状态码(不用 `errors.Is`,Python 子类靠 status_code 比对):
```python
try:
    c.tasks.submit(req)
except wau_sdk.NotFoundError as e:
    # e.status_code 自动 = 404
    ...
except wau_sdk.UnauthorizedError as e:
    # e.status_code 自动 = 401
    ...
except wau_sdk.APIError as e:
    logger.error(f"unexpected: status={e.status_code} code={e.code}")
```

⚠️ **不要用 builtin `NotImplementedError`** — SDK 用了 `WauNotImplementedError` 别名避免与 Python builtin 撞名。

### 7.3 9 Handshake Sentinel(per v0.8.0 M5-1 B.1)

| 异常类 | 状态码 | code | 触发 |
|---|---|---|---|
| `HandshakeInsufficientTrustError` | 403 | `INSUFFICIENT_TRUST` | Agent 信任分不足 |
| `HandshakeAgentNotFoundError` | 404 | `AGENT_NOT_FOUND` | Agent 不存在 |
| `HandshakeTenantMismatchError` | 403 | `TENANT_MISMATCH` | 跨 tenant |
| `HandshakeRateLimitedError` | 429 | `RATE_LIMITED` | 频次限制 |
| `HandshakeProtocolNotSupportedError` | 400 | `PROTOCOL_NOT_SUPPORTED` | 协议不支持 |
| `HandshakeSessionNotFoundError` | 404 | `SESSION_NOT_FOUND` | Session 不存在 |
| `HandshakeAgentNoEndpointError` | 404 | `AGENT_NO_ENDPOINT` | Agent 无 endpoint |
| `HandshakeInvalidProtocolError` | 400 | `INVALID_PROTOCOL` | 协议格式错 |
| `HandshakeInvalidRequestError` | 400 | `INVALID_REQUEST` | 请求格式错 |

### 7.4 wau-edge 错误码(透传到 SDK,Stage 3.1 实测)

| wau-edge 错误 | 状态码 | 触发 |
|---|---|---|
| `INSUFFICIENT_TRUST` | 403 | Agent 信任不足 |
| `AGENT_NOT_FOUND` | 404 | Agent 不存在 |
| `TENANT_MISMATCH` | 403 | 跨 tenant 访问 |
| `RATE_LIMITED` | 429 | 频次限制 |
| `PROTOCOL_NOT_SUPPORTED` | 400 | 协议不支持 |
| `MODEL_NOT_FOUND` | 404 | Model 不在 wau-llm-router universe 配置中(per [[project-v0-9-0-M3-§3.7-chat-sdk-4langs-2026-06-30]]) |

### 7.5 自定义 Client 校验

| 异常 | 触发 |
|---|---|
| `ValueError` | `model=""` / `messages=[]` 客户端拦截(不发请求) |
| `ValueError` | `AuthConfig.__post_init__` 缺 `shared_secret` / `agent_name` / `tenant_id` |
| `ValueError` | `RetryConfig.__post_init__` `max_backoff_ms < initial` / `jitter` 不在 [0,1] |

---

## 8. 版本与变更

### 8.1 当前版本

**v1.1.0**(v0.9.0 "Acorn" Stage 3.2 完整化,2026-07-02,SDK 同步发版 per [[project-v0-8-0-GA-2026-07-13]])
- ✅ 11 HTTP 端点 × 2 同步/异步(per Stage 0 4 SDK 5/5 字段对齐)
- ✅ Stage 3.1 #1+#2:`AuthConfig.tenant_id` 必填(per [[project-v0-9-0-blocker-fix-1-plus-2-2026-07-01]])
- ✅ Stage 3.1 #5:Python SDK Chat e2e 2xx 实测(`chatcmpl-2a19212e` / 13 tokens)
- ✅ Bot 5 方法 interface 4 SDK 完全统一(per D13)
- ✅ Handshake 9 sentinel error 4 SDK 一致

### 8.2 升级指南(v0.7.0 → v1.1.0)

```bash
pip install --upgrade wau-sdk>=1.1.0
```

**破坏性变更**:
1. **AuthConfig.tenant_id 必填**(per Stage 3.1 #1):v0.7.x 时代可选,v1.1.0 必填。
   修复:`auth = AuthConfig(..., tenant_id="tenant-A", shared_secret=os.environ[...].encode())`
2. **错误子类化**:`wau_sdk.NotImplementedError` 是 WauError 子类,**跟 builtin NotImplementedError 撞名**。
   修复:`from wau_sdk import WauNotImplementedError as SDKNotImplementedError`
3. **Chat DTO**:v0.8.0 时代 Chat 走 `Tasks().submit` 旧路径,v1.1.0 必须用 `chat.completions` 直连 wau-edge。

**非破坏**:
- ✅ `Client` / `AsyncClient` 双接口仍兼容 `with` / `async with` context manager
- ✅ Bot 5 方法接口不变
- ✅ 11 端点路径不变

### 8.3 v1.2.0+ 路线(不做的)

- ❌ Streaming SSE(留 v1.2.0):用 `CompletionsStream(req)` 替换
- ❌ Slack / WhatsApp / 钉钉 / 飞书 / Email bot(留 v1.0.0)
- ❌ IntentService gRPC 4 方法实装(留 M3.1)
- ❌ Thompson Update 给 SDK 暴露(留 v1.0.0 后)

### 8.4 历史

| 版本 | 日期 | 关键变更 |
|---|---|---|
| v0.6.0-preview.1 | 2026-06-14 | W6.7-W6.11:11 端点 + 异步镜像 + 6 retry/circuit 翻译 + 4 docs + 4 examples |
| v1.0.0 GA | 2026-06-19 | W7.7:Public API stable + deprecation policy 文档校准 |
| **v1.1.0** | **2026-07-13**(target) | **v0.9.0 sync:Stage 3.1 #1+#2 tenant_id fix + #5 Python SDK e2e + Stage 3.2 doc 完整化** |

---

## 链接

- [README.md](./README.md) — 入口
- [QUICKSTART.md](./QUICKSTART.md) — 15 分钟跑通
- [DEPLOY.md](./DEPLOY.md) — PyPI 发布
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 模块 + 4 SDK 对齐
- [CHANGELOG.md](./CHANGELOG.md) — 版本变更
- [docs/api.md](./docs/api.md) — 历史 v0.6.0-preview.1(已迁根,顶部 redirect)
- [docs/auth.md](./docs/auth.md) — HS256 + JWT 详细
- [docs/retry_circuit.md](./docs/retry_circuit.md) — 重试 + 熔断详细
- [docs/quickstart.md](./docs/quickstart.md) — Bot 5 分钟上手
- [examples/](./examples/) — 7 个 runnable example
- [FAQ.md](./FAQ.md) — 故障排查(10 通用 + 5 Python 特定)

---

**维护**:Claude + youhaoxi(Stage 3.2 SDK doc 完整化,2026-07-02)
**WAU 业务代码改动 = 0**(纯文档,不改 .py)
