## [Unreleased] — v1.3.0 "bot_uuid field add (W7.1, 2026-07-09)"

### Added

- `bot_uuid` (UUID v4, server-assigned) field added to `Account` + `RegisterBotRequest` dataclasses in `src/wau_sdk/bot/common/account.py`
- Per D78/D79/D80 decisions; D60 additive, 0 breaking change
- Cross-SDK JSON byte-equal alignment per D13
- 老 SDK v1.2.0 向后兼容(server 自动从 bot_id slug 寻址并生成 bot_uuid)
- 0 unit tests added (W7.2 will add 15 mock e2e tests for 5 platforms × 3 cases)

### Compatibility

- 100% 保持向后兼容 — `bot_uuid` 字段 default = "",老 client 不传 = server 自动生成
- 老 9 字段(`account_id, tenant_id, bot_id, public_bot_id, owner_user_id, channel_type, channel_config_id, created_at, updated_at`) 0 改
- 老 `bot_id` slug 语义不变(tenant-local, client-supplied)
- 跟 D66=B RBAC 兼容(`owner_user_id` 维持 string)

---

## [Unreleased] — v1.3.2 "MCP client add (D87.6, 2026-07-11)"

### Added

- ⭐ New `mcp/` submodule: 5 files + tests, ~1500 LoC
  - `src/wau_sdk/mcp_client.py` — `MCPClient` (sync) + `AsyncMCPClient` (async) + 8 sync tool wrapper methods
  - `src/wau_sdk/mcp_dto.py` — 8 DTOs (`Message` / `Part` / `Task` / `Artifact` / `AgentCard` / `ExtendedAgentCard` / `HealthCheckResult` / `ListTasksFilter`+`ListTasksResult` / `PushConfig`+`PushConfigResult`)
  - `src/wau_sdk/mcp_errors.py` — `RPCError` + 5 spec code (`-32700`/`-32600`/`-32601`/`-32602`/`-32603`) + 3 MCP-specific code (`-32001` ~ `-32003`)
  - `src/wau_sdk/mcp_tools.py` — 10 tool name constants + `ALL_TOOL_NAMES` tuple + `is_streaming_tool` helper
  - `src/wau_sdk/mcp_auth.py` — `set_bearer_token` / `build_headers` helpers
  - `tests/test_mcp_client.py` — 38 unit tests covering 8 sync tool round-trip + W5 stub + error path + auth + helpers + async + concurrent
- 8 sync MCP tool wrappers: `health_check` / `parse_agent_card` / `send_message` / `get_task` / `list_tasks` / `cancel_task` / `create_task_push_notification_config` / `get_extended_agent_card`
- 2 SSE streaming tool (`stream_message` / `subscribe_to_task`) deferred to W5+ (W3-launch-SOP §3.3 拍板)
- Per D87 ⭐⭐ decision; D60 additive (0 改老 `chat.py` / `bot/` / `ucp_*` / `_client.py` etc)
- Cross-SDK JSON byte-equal alignment per D13
- Bearer token 注入 OAuth 2.0 identity_linking (per D78/D79/D80)
- W5 stub 友好路径(per W3-launch-SOP 渐进接入)

### Compatibility

- 100% 向后兼容 — 老 SDK v1.3.0 / v1.3.1 client 不感知 mcp/ 新增
- 0 breaking change to existing APIs
- JSON-RPC 2.0 envelope (`{jsonrpc: "2.0", method: "tools/call", params: {name, arguments}, id}`) 跟 wau-go-sdk `mcpclient/` 字段 1:1 对齐

---

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

## [Unreleased] — v1.3.3 "UCP client (W3, 2026-07-11, per D88)"

### Added

- 新 submodule(`ucp_client.py` / `ucp_dto.py` / `ucp_errors.py` / `ucp_stripe.py`),跟 `chat.py` / `bot/` 同级独立模块(D60 additive)
- `UCPClient` + `AsyncUCPClient`:11 commerce tool wrapper(走 JSON-RPC 2.0 over HTTP,endpoint `POST {base_url}/ucp`):
  - `list_products(filter: ListProductsFilter | None) -> ListProductsResult`
  - `get_product(product_id: str) -> Product`
  - `search_products(query: str, limit: int = 10) -> SearchProductsResult`
  - `add_to_cart(product_id: str, quantity: int = 1) -> Cart`
  - `get_cart(cart_id: str) -> Cart`
  - `remove_from_cart(cart_id: str, line_item_id: str) -> Cart`
  - `create_checkout_session(cart_id: str) -> CheckoutSession` — W3 stub,W5+ Stripe
  - `confirm_payment(checkout_session_id: str) -> PaymentConfirmation` — W3 stub,W5+ Stripe
  - `get_order(order_id: str) -> Order`
  - `list_orders(user_id: str, filter: ListOrdersFilter | None) -> ListOrdersResult`
  - `cancel_order(order_id: str) -> CancelOrderResult` — W5+ Stripe refund
- 8 commerce DTO(`@dataclass`,不是 Pydantic)— `tenant_id` 字段(per D65 multi-tenant)
- 11 ToolXxx 常量(`TOOL_LIST_PRODUCTS` … `TOOL_CANCEL_ORDER`)
- `RPCError` + 5 spec code + 5 UCP-specific code(`-32101 ~ -32105` 跟 MCP `-32001 ~ -32003` 错开)
- `RPCError.from_dict` / `is_not_found(err)` / `is_stripe_error(err)` helper
- `set_bearer_token` / `set_tenant_id` helper(per D78/D79/D80 bearer + D65 tenant 隔离)
- `is_stripe_path(tool_name)` Stripe 路径 helper(per D88.6)
- `PAYMENT_STATUS_*` 4 常量(`SUCCEEDED` / `FAILED` / `PROCESSING` / `PENDING`)
- 25 unit tests(httpx.MockTransport mock kernel + 11 tool round-trip + W3 stub 验证 + error path + auth helper + stripe helper + 4 async)100% PASS

### Compatibility (D60 additive)

- 0 改老 SDK(`chat.py` / `bot/` / `_client.py` / `_transport.py` 等全部 0 触碰)
- 走独立 JSON-RPC 2.0 client(`_call_tool` 通用 dispatch),不耦合 `wau_sdk._client.Client.do_request`(跟 `chat.py` / `bot/` 同样的"独立 submodule" pattern)
- W3 stub:`create_checkout_session` + `confirm_payment` 走 kernel `ErrNotImplemented` → SDK 抛 `NotImplementedError` 友好提示"W5 Stripe 集成中"
- Stripe SDK 0 直接依赖(等 kernel `ucp_stripe.go` 落地 W5+)

### Reference

- D88 拍板(UCP server):[stage2/2026-07-10-D86-D87-D88-protocol-gateway-decision](https://github.com/wau-network/WAU-develop/blob/main/develop-log/kernel/v1.0.0/stage2/2026-07-10-D86-D87-D88-protocol-gateway-decision.md)
- 5 SDK UCP client 详设:[process/2026-07-11-W3-UCP-client-SDK-design](https://github.com/wau-network/WAU-develop/blob/main/develop-log/kernel/v1.0.0/process/2026-07-11-W3-UCP-client-SDK-design.md)
- UCP Stripe design:[process/2026-07-11-W3-UCP-Stripe-Checkout-design](https://github.com/wau-network/WAU-develop/blob/main/develop-log/kernel/v1.0.0/process/2026-07-11-W3-UCP-Stripe-Checkout-design.md)
- 兄弟: wau-go-sdk v1.3.3 `ucpclient/` 已落地 (D88.5),跟本模块同步实跑
- benny 迁移澄清:kernel UCP 是通用 commerce 垂直协议层,benny 保持独立 demo plugin(2026-07-11 user 拍板)

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
