# 重试 + 熔断

wau-python-sdk 默认启用两个保护性装饰器,自动应用到所有 4 核心服务的 HTTP 调用。

## 重试(指数退避 + 抖动)

**默认配置**(`RetryConfig` 默认值):

| 字段 | 默认值 | 说明 |
|---|---|---|
| `max_retries` | 3 | 总共调 4 次(1 + 3 重试) |
| `initial_backoff_ms` | 200 | 第一次退避 |
| `max_backoff_ms` | 5000 | 退避上限 |
| `jitter` | 0.2 | ±20% 随机抖动(防雪崩) |
| `retry_on` | `[500, 502, 503, 504, 429]` | 触发重试的状态码 |

**重试规则**(`is_retryable` 函数):
- 5xx + 429 → 重试
- 4xx(非 429)→ **不**重试(业务错,服务端没责任)
- 网络错 / 超时 → 重试
- `context.Canceled` / `DeadlineExceeded` → 立即停止,不重试
- `CircuitOpenError` → **不**重试(避免雪崩)

**总耗时估算**:3 次重试,backoff 200ms + 400ms + 800ms = **~1.4s**(无 jitter)

**关闭重试**:
```python
import wau_sdk
c = wau_sdk.Client("http://localhost:18400", wau_sdk.ClientOptions(
    retry=wau_sdk.RetryConfig(max_retries=0),  # 不重试
))
```

**自定义**:
```python
c = wau_sdk.Client("http://localhost:18400", wau_sdk.ClientOptions(
    retry=wau_sdk.RetryConfig(
        max_retries=5,
        initial_backoff_ms=100,
        max_backoff_ms=10_000,
        jitter=0.3,
        retry_on=[502, 503, 504],
    ),
))
```

## 熔断(集成 wau-circuit)

**默认配置**(`CircuitConfig` 默认值):

| 字段 | 默认值 | 说明 |
|---|---|---|
| `enabled` | True | 总开关 |
| `failure_threshold` | 5 | 5 次失败后开熔断 |
| `open_timeout_ms` | 30000 | 熔断开 30s 后转 HalfOpen |

**熔断状态机**(参考 [wau-circuit](https://github.com/XploreAlpha/wau-circuit)):

```
Closed ──(5 failures)──> Open
   ^                        │
   │                        │ 30s 超时
   │                        ▼
   └─(1 success)─── HalfOpen
                       │
                       │ 1 failure
                       ▼
                     Open
```

**短路行为**:
- Open 状态下,所有 HTTP 请求立即返 `wau_sdk.CircuitOpenError`(不调底层 transport)
- 节省 kernel 端的无效请求

**记录规则**(`is_circuit_failure`):
- 5xx → 计入失败
- 4xx → **不**计入(业务错,服务可用)
- 网络错 / 超时 → 计入

**查询当前状态**(debug / metrics):
```python
state = c.circuit_state()  # "closed" | "open" | "half-open"
```

**关闭熔断**(测试 / 调试):
```python
c = wau_sdk.Client("http://localhost:18400", wau_sdk.ClientOptions(
    circuit=wau_sdk.CircuitConfig(enabled=False),
))
```

## 装饰器链调用顺序

```
Caller → Service method → Transport.do → raise on 4xx/5xx
                                ↓
                          Retrier.do (tenacity)
                                ↓
                          is_retryable? — N → raise original err
                                Y
                          max_retries+1 calls
                                ↓ exhausted
                          MaxRetriesError
```

(熔断是 wau-python-sdk 翻译 wau-circuit 的内部状态机,不显式在调用链中 — 5xx/网络错累积到阈值自动 open)

## 集成测试示例

```python
import wau_sdk
import httpx
import respx
import threading

calls = 0
with respx.mock(base_url="http://mock") as router:
    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "ok", "version": "v0.6.0", "uptime": 1.0, "redis": "connected"})
    router.get("/health").mock(side_effect=handler)

    c = wau_sdk.Client("http://mock", wau_sdk.ClientOptions(
        retry=wau_sdk.RetryConfig(
            max_retries=3,
            initial_backoff_ms=10,
            max_backoff_ms=100,
            jitter=0,
            retry_on=[503],
        ),
        circuit=wau_sdk.CircuitConfig(enabled=False),
    ))
    h = c.agents.health()  # 503 + 503 + 200 = 3 calls
    assert h.status == "ok"
    assert calls == 3
```

## 行为对齐

wau-python-sdk 的熔断行为跟 [wau-circuit](https://github.com/XploreAlpha/wau-circuit) **字节级一致**(`_circuit.py` 154 行 Go → 150 行 Python 翻译)。Go/TS SDK 也用同一份状态机,3 SDK 行为对齐由"故障注入黄金测试"兜底(详见 [ADR-0003](https://github.com/XploreAlpha/wau-go-sdk/blob/main/docs/adr/0003-circuit-integration.md))。
