# Quickstart

5 分钟接入 WAU 智能调度内核。

## 安装

```bash
pip install wau-sdk==0.6.0-preview.1
```

## Hello World(同步)

```python
import wau_sdk

with wau_sdk.Client("http://localhost:18400") as c:
    resp = c.tasks.submit(wau_sdk.SubmitRequest(
        prompt="What is the capital of France?",
        timeout_ms=30000,
    ))
    print(f"✅ 选中 {resp.selected_agent}: {resp.response}")
```

## Hello World(异步)

```python
import asyncio
import wau_sdk

async def main():
    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        resp = await c.tasks.submit(wau_sdk.SubmitRequest(
            prompt="What is the capital of France?",
        ))
        print(f"✅ 选中 {resp.selected_agent}: {resp.response}")

asyncio.run(main())
```

## 核心 4 服务

```python
c = wau_sdk.Client("http://localhost:18400")

# 1. Kernel: 元信息 / 健康
info = c.kernel.info()           # GET /kernel/info
health = c.kernel.health()       # GET /health

# 2. Agents: CRUD + 状态 + 评分 + 心跳
agents = c.agents.list(wau_sdk.PageOptions(page=1, pageSize=10))  # GET /registry/agents
status = c.agents.get("jarvis")                                      # GET /registry/agents/jarvis/status
score = c.agents.score("jarvis")                                    # GET /registry/agents/jarvis/score
c.agents.register(wau_sdk.AgentRegisterRequest(name="...", url="...")) # POST
c.agents.deregister("old")                                          # DELETE
c.agents.heartbeat("my-agent")                                      # POST
c.agents.report_load("my-agent", wau_sdk.AgentLoad(...))             # POST

# 3. Tasks: 提交 / 查询 / 模拟
resp = c.tasks.submit(wau_sdk.SubmitRequest(prompt="...", timeout_ms=30000))  # POST /registry/tasks/submit (L4)
decision = c.tasks.simulate(wau_sdk.SubmitRequest(prompt="..."))              # POST /registry/tasks/simulate (L3)
task = c.tasks.get("task-001")                                                 # GET /registry/tasks/task-001

# 4. Intent: gRPC stub (P2 推 M3.1)
# c.intent.recommend("...", top_k=3)  # 暂返 NotImplementedError
```

## 常用配置

```python
import os
import wau_sdk
from wau_sdk import AuthConfig, Role, RetryConfig, CircuitConfig

c = wau_sdk.Client(
    "http://localhost:18400",
    wau_sdk.ClientOptions(
        timeout_ms=30_000,                # 默认 30s
        retry=RetryConfig(max_retries=3), # 指数退避 3 次 (200ms-5s, ±20% jitter)
        circuit=CircuitConfig(            # 熔断 5 failures / 30s recovery
            failure_threshold=5,
            open_timeout_ms=30_000,
        ),
        auth=AuthConfig(                   # 启用 HS256 鉴权
            agent_name="my-agent",
            shared_secret=os.environ["WAU_JWT_SECRET"].encode(),
            role=Role.TRUSTED_AGENT,
        ),
    ),
)
```

## 错误处理

```python
import wau_sdk
from wau_sdk import NotFoundError, UnauthorizedError, CircuitOpenError, MaxRetriesError, APIError

try:
    resp = c.tasks.submit(...)
except NotFoundError as e:
    # 404 业务处理
    ...
except UnauthorizedError:
    # 401 重启鉴权
    ...
except CircuitOpenError:
    # 熔断开,等 30s 再试
    ...
except MaxRetriesError as e:
    # 重试耗尽,上报监控(e.last_error 是最后一次的异常)
    logger.error(f"5xx after retries: {e.last_error}")
except APIError as e:
    # 其他 API 错(2xx 也可能,e.status_code >= 400)
    ...
```

## 分页迭代

```python
# 一次拉 1 页
page1 = c.agents.list(wau_sdk.PageOptions(page=1, pageSize=10))
# 翻页遍历
for agent in c.agents.iter(wau_sdk.PageOptions(pageSize=10)):
    print(agent.name, agent.trust, agent.status)
```

## 下一步

- [API 参考](./api.md)— 全部 11 端点 + DTO
- [鉴权 HS256 + JWT](./auth.md)
- [重试 + 熔断](./retry_circuit.md)
- [examples/](../examples/)— 4 个可运行示例
- [ADR](../adr/)— 架构决策记录(wau-go-sdk 仓)
