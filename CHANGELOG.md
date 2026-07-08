## [Unreleased] — v1.0.0 "Phoenix" M11 W8 (2026-07-08) → v1.3.1

### Added

#### M2 OAuth (ClientCredentials)
- `OAuthClient` + async `OAuthClient`(token refresh + scope)
- `ClientOptions.wau_registry_url: str = "http://localhost:18401"` additive(D60)
- 15 unit tests PASS

#### M11 P2 + P4 agent_runtime
- `sync + async publish_agent(manifest, bundle_path) → SkillPublishResponse`
- `SkillPublishResponse` DTO(`name, version, entrypoint, bundle_size, bundle_sha`)
- `agent_runtime.py` 全 new service module(584 行)
- 4 unit tests PASS

### Compatibility

- API 100% 保留
- 仅 additive 新增 OAuth + publish_agent

---

## [v1.2.0] - 2026-07-02 (v0.9.0 GA)

### Highlights

- v1.2.0 (与 v0.9.0 "Acorn" 同步发版) + Stage 3.1 #10 Chat SSE streaming + 5 字段 100% 保留 + SDK doc 完整化
- 详见 GA 收口报告:~/WAU-develop/develop-log/kernel/v0.9.0/wrapup/2026-07-02-PROGRESS-v0.9.0-GA-CLOSURE.md

### Compatibility

- API 100% 保留
- LLMDecision 字段 100% 保留

# Changelog

## v1.0.0 (2026-06-19) — GA

> 🟢 **Amber W2 Day 4: Python SDK 1.0 GA**
> 95/95 tests pass · 88% 覆盖率 · 0 breaking changes vs 0.6.0-preview.1

### 升级说明

- 0.6.0-preview.1 → 1.0.0:无 API 变化,只是去掉 preview 标签
- 1.0.0 = 稳定 API 保证(以后 1.x.y 只做 bug fix,1.x.0+ 才加新功能)
- pip install: `pip install wau-sdk==1.0.0`

### 已就位(从 v0.6.0-preview.1 继承)

- HTTP API 11 端点 × 2 同步/异步 = 22 方法
- 4 场景契约 25/25 过
- 装饰器链(translate / agentrec / circuit)
- 4 service 客户端(Kernel / Registry / Intent / Circuit)
- CI workflow(GitHub Actions)
- 4 examples(basic / async / decorators / circuit-breaker)
- docs/ 全套

## v0.6.0-preview.1 (2026-06-14)

> 🔶 Carnelian M3 W6 — 完整 Python SDK
> 抽取自 wau-cli/internal/client/(337 行, 4 文件) Go 版,扩展 Python 生态

### 新增

- **HTTP API 11 端点 × 2 同步/异步 = 22 方法**(P1 阶段):
  - `KernelService`: Info + Health
  - `AgentsService`: Health + List + Iter + Get + Score + Register + Deregister + Heartbeat + ReportLoad
  - `TasksService`: Submit + Simulate + Get
  - `IntentService`: 4 个 gRPC stub(M3.1 实装,目前返 NotImplementedError)
- **typed errors**:`APIError` 基类 + 6 个 4xx 子类(NotFoundError/UnauthorizedError/ForbiddenError/BadRequestError/ConflictError/APIError)
- **重试装饰器**:指数退避 + 抖动(tenacity),默认 3 次 / 200ms-5s,只重试 5xx/429 + 网络错
- **熔断装饰器**:集成 wau-circuit(154 行 Go → ~150 行 Python 翻译),per-Client 实例,5 failures / 30s recovery
- **HS256 鉴权**:JWT Bearer(PyJWT),5min exp,UUID v4 jti 防重放
- **SubmitRequest 字段以 kernel 真相源为准**:`{prompt, timeout_ms}`,**不是** wau-cli 旧 DTO(`{message, sourcePeer, ...}`)
- **分页迭代器**:`Iter(opts) -> Iterator[Agent]`,Go 1.23+ 泛型等价物
- **5 场景契约测试**:clinical / france / pain / sales / rare-disease(从 [wau-go-sdk 黄金 JSON](https://github.com/XploreAlpha/wau-go-sdk/tree/main/tests/contract-golden) 复用,3 SDK 行为字节级对齐)

### 测试

- **95 passed in 3.36s** (95 个单测 + 5 场景契约 + 黄金 schema 验证)
- **覆盖率 88%** (超过 plan §10.2 80% 门槛 8%)

| 模块 | 覆盖率 |
|---|---|
| `types.py` / `__init__.py` / `_circuit.py` | 100% |
| `_retry.py` | 98% |
| `_auth.py` | 91% |
| `_client.py` | 88% |
| `_errors.py` / `_options.py` | 86% |
| `agents.py` | 84% |
| `tasks.py` | 80% |
| `_transport.py` | 78% |
| `kernel.py` | 76% |
| `intent.py` | 71% |

### 修复的真 bug(M3 W6 期间)

1. **`_retry.py`**: `retry_if_exception_type` 误捕获 4xx → 改用 `retry_if_exception(is_retryable)` 谓词
2. **`_retry.py`**: Tenacity `AsyncRetrying` 不支持 `for` → 改用 `async for`
3. **`_retry.py`**: MaxRetries=0 仍抛 `MaxRetriesError` → 加 `max_retries > 0` 检查
4. **`agents.py`**: `AgentListResponse.agents` 是 list[dict](dataclass 不自动转嵌套) → 加显式 dict → Agent 转换
5. **`agents.py`**: `get()` load 字段 dict 不转 AgentLoad → 转换
6. **`kernel.py`**: 字段名 camelCase(`startTime`) → 显式转 snake_case(用 `data.get(...)`)
7. **`_errors.py`**: 4xx 子类接口与 `APIError` 基类冲突 → 用闭包工厂 + `__init__` 重写
8. **`_retry.py`**: `tenacity.AsyncRetrying` 不是 iterable → 用 `async for` 而非 `for`

### 文档

- `README.md` — 项目状态 + 快速开始
- `docs/quickstart.md` — 5 分钟接入(同步 + 异步)
- `docs/api.md` — 完整 API 参考(11 端点 + DTO + 错误)
- `docs/auth.md` — HS256 鉴权指南
- `docs/retry_circuit.md` — 重试 + 熔断详解

### CI

- `.github/workflows/ci.yml` — pytest + ruff + mypy + coverage (4 Python 版本 × 2 OS)

### Examples

- `examples/list_agents/main.py` — 列出在线 agents
- `examples/submit_task/main.py` — 提交 L4 任务
- `examples/heartbeat_loop/main.py` — agent 端定时心跳(60s 间隔)
- `examples/five_scenarios/main.py` — 跑 5 场景契约

### 已知限制(P2/P3 推迟)

- ❌ **gRPC client (P2)**:所有 `IntentService` 方法返 `NotImplementedError`
- ❌ **A2A/AFP 协议层 (P3)**:SDK 不暴露 Protocol interface
- ❌ **30 个 gRPC RPC** (Scheduler / Scoring / Store / Circuit):P2 阶段做
- ❌ **wau-cli 老 client 替换**:等 M3 收尾(2026-07-05)

### 升级指引(从 wau-cli 老 client)

```python
- from wau_cli.internal.client import NewClient
+ import wau_sdk

- client = NewClient(base_url=..., role=...)
+ client = wau_sdk.Client("http://localhost:18400", wau_sdk.ClientOptions(
+     auth=wau_sdk.AuthConfig(agent_name="...", shared_secret=...),
+ ))

- resp = client.SubmitTask(prompt=..., source_peer=...)
+ resp = client.tasks.submit(wau_sdk.SubmitRequest(
+     prompt=..., timeout_ms=30000,
+ ))
```

## [Unreleased] — v1.0.0 "Phoenix" M10 W8 (2026-07-08)

### Added

#### M10 N1 — Bot 注册 DTO + BotsService 公共 ABC

- `wau_sdk/bot/common/account.py`(NEW,~114 行):
  - `Account` dataclass 字段跟 wau-go-sdk 100% 一致(per D13)
  - `new_account(...)` factory + `public_bot_id_of(...)` helper
  - `RegisterBotRequest` / `UpdateBotRequest` / `ListBotsFilter` dataclasses
- `wau_sdk/bot/common/bots_service.py`(NEW,~60 行):
  - `BotsService` ABC:register / get / update / list / delete
  - 2 sentinel errors:`BotNotFoundError` / `BotAlreadyExistsError`
- `wau_sdk/bot/common/__init__.py` 加 7 export
- `wau_cli bot` 子命令保持 0 行新增(per W7 launch subtask 拍板,等子项 2 完工后加)

#### Compatibility (D60)

- `Bot` ABC / `IncomingMessage` / `OutgoingMessage` / `BotBuilder` 0 改
- 字段 snake_case,D13 跨 SDK 一致

#### M4 OAuth 增强 (2026-07-08)
- `RefreshableTokenStore.refresh_token()` 公开方法(force=True 绕过双检)
- `RefreshableTokenStore.current_pair() -> TokenPair` dataclass
- `PKCEClient` + `PKCEConfig` + `generate_pkce_challenge()` Authorization Code + PKCE
- `_PKCEOnlyStore` 公共 client 路径专用 store(无 oc.refresh 兜底)
- 0 改老 OAuthClient + 老 RefreshableTokenStore(D60 additive)
- 4 unit tests PASS(refresh_token + PKCE challenge + URL + exchange)
