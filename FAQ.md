# wau-python-sdk 故障排查(FAQ)

> **版本**:v1.1.0(v0.9.0 "Acorn" Stage 3.2,2026-07-02)
> **范围**:10 通用问题 + 5 Python 语言特定问题 = 15 Q&A
> **配套**:`docs/retry_circuit.md`(重试熔断详解)+ `docs/auth.md`(鉴权详解)

---

## 通用问题(10 Q,跨 4 SDK 适用)

### Q1: 401 Unauthorized / invalid tenant

**症状**:
```
wau_sdk.errors.UnauthorizedError: WauAPIError(status=401, code=unauthorized,
request_id=..., message=..., body="{"error":"tenant_id missing"}")
```

**原因**:
- `Signer.sign()` 没签 `tenant_id` claim(per Stage 3.1 #1 修复前的旧 bug)
- `wau-edge` JWT secret 跟 SDK `AuthConfig.shared_secret` 不一致
- `AuthConfig.tenant_id` 是空字符串

**修复**:
```python
import os
import wau_sdk

# 1. 必填 TenantID(空字符串 → AuthConfig.__post_init__ raise ValueError)
auth = wau_sdk.AuthConfig(
    role=wau_sdk.Role.EXTERNAL_AGENT,
    agent_name="my-agent",
    tenant_id="tenant-A",  # ← 必填,per Stage 3.1 #1
    shared_secret=os.environ["WAU_EDGE_JWT_SECRET"].encode(),
)

# 2. JWT secret 一致(server 端 wau-edge/internal/auth/jwt.go 校验)
#    wau-edge 默认空 secret = 严格 reject(per #1+#2 修复)
#    必须 env WAU_EDGE_JWT_SECRET=xxx 启动 wau-edge

# 3. 验证
import requests
token = wau_sdk._auth.Signer(auth).sign()
r = requests.post(
    "http://localhost:18402/v1/chat/completions",
    headers={"Authorization": f"Bearer {token}"},
    json={"model": "wau-default", "messages": [{"role": "user", "content": "hi"}]},
)
print(r.status_code)  # 期望:200
```

**进度报告**:[[project-v0-9-0-blocker-fix-1-plus-2-2026-07-01]]

---

### Q2: connection refused :18402 / :18400 / :18404

**症状**:
```
wau_sdk.errors.APIError: WauAPIError(status=...,
  message=connection refused, body=...)
# 或 httpx.ConnectError: [Errno 111] Connection refused
```

**原因**:wau-core-kernel(:18400)/ wau-edge(:18402)/ wau-llm-router(:18404)未启。

**修复**:
```bash
# 走 §3.8 onelab 脚本(4 步基线)
bash /home/inamoto888/WAU-develop/develop-log/kernel/v0.9.0/v0.9.0-onelab-deploy.sh up

# 或单独启(每个进程一个终端 / tmux pane)
cd /home/inamoto888/project/wau-edge
go run ./cmd/wau-edge -config configs/edge.yaml &

cd /home/inamoto888/project/wau-llm-router
go run ./cmd/wau-llm-router -config configs/router.yaml &

# 验证端口活
curl http://127.0.0.1:18402/health     # wau-edge
curl http://127.0.0.1:18400/health     # wau-core-kernel
grpcurl 127.0.0.1:18404 list           # wau-llm-router gRPC
ss -tlnp | grep -E ":1840[0-4]"
```

**端口速查**:

| 服务 | HTTP | gRPC | 备注 |
|---|---|---|---|
| wau-core-kernel | :18400 | :18401 | SDK baseURL 默认 |
| wau-edge | :18402 | :18403 | Chat completions 用 |
| wau-llm-router | :18403 | :18404 | HTTP/gRPC 不同协议层不冲突 |

---

### Q3: TimeoutError / context deadline

**症状**:
```
httpx.TimeoutException: timeout
# 或 (异步) asyncio.TimeoutError
```

**原因**:`ClientOptions.timeout_ms` < kernel 处理时间。

**修复**:
```python
import wau_sdk

# 1. 调高 timeout(默认 30000ms = 30s)
opts = wau_sdk.ClientOptions(timeout_ms=60_000)

# 2. 长 task 用 SubmitRequest.timeout_ms
with wau_sdk.Client("http://localhost:18400", opts) as c:
    resp = c.tasks.submit(wau_sdk.SubmitRequest(
        prompt="long task",
        timeout_ms=300_000,  # 5 分钟
    ))

# 3. async 上下文用 asyncio.wait_for 单次覆盖
import asyncio
async def main():
    async with wau_sdk.AsyncClient("http://localhost:18400", opts) as c:
        resp = await asyncio.wait_for(
            c.tasks.submit(wau_sdk.SubmitRequest(prompt="hi")),
            timeout=90.0,  # 90s
        )
```

---

### Q4: `Bot.start()` 卡住 / 不响应

**症状**:`await bot.start()` 返回但 Telegram/Discord/Webhook 不响应消息。

**原因**:
- Bot token 没设 / 不对(env var 没读到)
- 网络不通(国内访问 Telegram/Discord API 需代理)
- `on_message` handler 没注册

**修复**:
```python
import os
import asyncio
from wau_sdk.bot.telegram import Bot

# 1. 检查 token
token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
print(token[:10])  # 应该以数字开头(格式:123456:ABC-DEF...)
if not token:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN 未设")

# 2. 检查网络
import httpx
r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
print(r.json())  # {"ok": true, "result": {...}}
# 国内:挂代理 export https_proxy=http://127.0.0.1:7890

# 3. SDK 端确认 on_message 注册
bot = Bot(token=token, tenant_id="tenant-A")

@bot.on_message
async def handle(msg):
    return wau_sdk.bot.common.OutgoingMessage(text=f"echo: {msg.text}")

await bot.start()
```

**注意**:Bot 类继承 `Bot(ABC)`,5 个方法(`start` / `stop` / `on_message` / `with_tenant` / `with_universe`)必须被覆盖(per D13)。

---

### Q5: 重试耗尽 / 熔断开

**症状**:
```
wau_sdk.errors.MaxRetriesError: max retries exceeded: ...
wau_sdk.errors.CircuitOpenError: circuit breaker is open
```

**原因**:上游 5xx / 网络抖动超过阈值。

**修复**:
```python
import wau_sdk

# 1. 调高 retry 阈值(默认 3 次)
opts = wau_sdk.ClientOptions(
    retry=wau_sdk.RetryConfig(
        max_retries=5,
        initial_backoff_ms=500,
        max_backoff_ms=10_000,
        retry_on=[500, 502, 503, 504, 429],
    ),
)

# 2. 调高熔断阈值(默认 5 失败)
opts = wau_sdk.ClientOptions(
    circuit=wau_sdk.CircuitConfig(
        failure_threshold=10,
        open_timeout_ms=60_000,
    ),
)

# 3. 临时禁用(测试用)
opts = wau_sdk.ClientOptions()
opts = wau_sdk.with_retry_no(opts)
opts = wau_sdk.with_circuit_disabled(opts)

# 4. 检查当前熔断状态
with wau_sdk.Client("http://localhost:18400", opts) as c:
    print(c.circuit_state())  # "closed" / "open" / "half-open"
```

**详细**:[docs/retry_circuit.md](./docs/retry_circuit.md)

---

### Q6: chat completions 返回 404 MODEL_NOT_FOUND

**症状**:
```
wau_sdk.errors.NotFoundError: WauAPIError(status=404, code=MODEL_NOT_FOUND, ...)
```

**原因**:`model` 字段不在 wau-llm-router universe 配置里。

**修复**:
```python
import wau_sdk

# Stage 1 MockModels 唯一接受 model 名(per §3.7 实测)
with wau_sdk.Client("http://localhost:18402", auth_opts) as c:
    resp = c.chat.completions(wau_sdk.ChatCompletionRequest(
        model="wau-default",  # ← Stage 1 唯一接受
        messages=[wau_sdk.ChatMessage(role="user", content="hi")],
    ))

# Stage 2 后真模型(gpt-4o / claude-haiku 等)需 wau-llm-router 配 universe
# per wau-llm-router/configs/router.yaml
```

---

### Q7: Thompson Update 失败 / reward out of range

**症状**(v1.0.0 才会触发,本期不适用):
```
wau_sdk.errors.BadRequestError: thompson: reward out of range [0,1]
```

**原因**:reward 超 [0,1] 范围。

**修复**:
```python
# reward ∈ [0, 1](v1.0.0 实装后)
update = {
    "model": "gpt-4o-mini",
    "reward": 0.85,  # 必须在 [0, 1]
}
```

---

### Q8: SDK 跨语言字段不一致

**症状**:Go SDK / Python SDK / TS SDK / Rust SDK 调同一端点,JSON 字段大小写 / 顺序不同。

**原因**:JSON 序列化策略差异(Go json.Marshal / Python json.dumps / TS JSON.stringify / Rust serde_json)。

**修复**:
- **Stage 0 收口**(2026-06-28):4 SDK 5/5 字段对齐(per [[project-v0-9-0-stage0-closure-2026-06-28]])
- **Stage 3.1 #4-#7** 实测:4 SDK Chat completions 全部 2xx 响应,字段字节级对齐
- **基准**:`wau-go-sdk/types.go` 为准(per ADR-0004),Python `types.py` 镜像对齐
- **小差异**:omitempty 字段顺序不影响语义,JSON parser 都容忍

```python
# Python 用 dataclass(slots=True) 字段顺序跟 Go 镜像对齐
@dataclass(slots=True)
class SubmitRequest:
    prompt: str                     # 必填
    timeout_ms: int | None = None   # 可选,跟 Go json tag 对齐
```

---

### Q9: 流式响应 / SSE 不工作

**症状**:`stream=True` 返回 non-streaming 响应或报错。

**原因**:v0.9.0 alpha **不支持 streaming**(per `chat.py` docstring + Stage 1 限制)。

**修复**:
```python
import wau_sdk

# v0.9.0 alpha:用 completions() non-streaming
with wau_sdk.Client("http://localhost:18402", auth_opts) as c:
    resp = c.chat.completions(wau_sdk.ChatCompletionRequest(
        model="wau-default",
        messages=[wau_sdk.ChatMessage(role="user", content="hi")],
        stream=False,  # ← 必须是 False
    ))

# v1.2.0+:用 completions_stream(req) (per §8.3 路线)
```

---

### Q10: TLS / CA 证书错误

**症状**:
```
ssl.SSLCertVerificationError: hostname mismatch / certificate verify failed
# 或 httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]
```

**原因**:自签证书 / CA bundle 缺失。

**修复**:
```python
import httpx
import wau_sdk

# 1. 注入跳过验证的 HTTP client(仅 dev!)
http_client = httpx.Client(
    verify=False,  # ⚠️ 仅 dev
    timeout=30.0,
)
opts = wau_sdk.ClientOptions(transport=http_client)
with wau_sdk.Client("https://wau.example.com", opts) as c:
    ...

# 2. 或配系统 CA bundle(生产推荐)
#    Linux: apt install ca-certificates
#    macOS: /Applications/Python\ 3.13/Install\ Certificates.command
http_client = httpx.Client(verify="/path/to/ca-bundle.crt", timeout=30.0)

# 3. 生产:用正规 CA 签名证书(Let's Encrypt 等)
```

---

## Python 语言特定问题(5 Q)

### Q11: `pip install` SSL 错

**症状**:
```
pip install wau-sdk==1.1.0
# Could not fetch URL https://pypi.org/simple/wau-sdk/:
#   There was a problem confirming the ssl certificate
```

**修复**:
```bash
# 1. 升级 pip + 配置国内镜像
python -m pip install --upgrade pip
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install wau-sdk==1.1.0

# 2. 临时绕过 SSL(仅 dev!)
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org wau-sdk==1.1.0

# 3. 检查 Python SSL 证书
python -c "import ssl; print(ssl.OPENSSL_VERSION)"
# Linux 需要:apt install libssl-dev python3-dev
# macOS:跑 /Applications/Python\ 3.13/Install\ Certificates.command
```

---

### Q12: `RuntimeError: no running event loop`

**症状**:
```
RuntimeError: no running event loop
# 或 RuntimeError: Cannot run the event loop while another loop is running
```

**原因**:AsyncClient 必须在 `asyncio` 协程内用,且不被嵌套。

**修复**:
```python
import asyncio
import wau_sdk

# ❌ 错:顶层 await
# await client.chat.completions(req)  # RuntimeError!

# ✅ 对:async with 上下文
async def main():
    async with wau_sdk.AsyncClient("http://localhost:18402", auth_opts) as c:
        resp = await c.chat.completions(req)
        print(resp.choices[0].message.content)

# ✅ 对:Jupyter / IPython 用 nest_asyncio
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

# ✅ pytest-asyncio fixture(pyproject.toml 已配 asyncio_mode="auto")
import pytest
@pytest.mark.asyncio
async def test_chat():
    async with wau_sdk.AsyncClient(...) as c:
        ...
```

---

### Q13: `aiohttp` / `httpx` session 泄漏

**症状**:长跑 bot / 服务,内存单调递增,文件描述符爆。

**原因**:没用 `with` / `async with` context manager,transport 没 close。

**修复**:
```python
import asyncio
import wau_sdk

# ✅ 推荐:用 context manager(自动 close)
async def serve():
    async with wau_sdk.AsyncClient("http://localhost:18400", auth_opts) as c:
        while True:
            resp = await c.tasks.submit(req)
            await asyncio.sleep(1)

# ✅ pytest-asyncio fixture 模式
import pytest
@pytest.fixture
async def client():
    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        yield c

async def test_x(client):
    resp = await client.tasks.submit(req)
```

**检查泄漏**:
```python
import gc
import httpx
gc.collect()       # 强制回收
print(len(gc.get_objects()))  # 观察增长趋势
```

---

### Q14: `asyncio.CancelledError` / 中断处理

**症状**:用户调 `task.cancel()` 但协程卡死 / 资源没释放。

**原因**:协程没监听 `CancelledError`,或阻断 IO 没设 timeout。

**修复**:
```python
import asyncio
import wau_sdk

# 1. 协程必须 try/except CancelledError 清理资源
async def serve():
    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        try:
            while True:
                resp = await c.tasks.submit(req)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("🛑 收到 cancel,清理中...")
            raise  # 必须 re-raise,Python 3.8+ CancelledError 是 BaseException 子类

# 2. 启动 + cancel
async def main():
    task = asyncio.create_task(serve())
    await asyncio.sleep(10)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("✅ 已取消")

asyncio.run(main())
```

---

### Q15: Bot 协程泄漏 / event loop 阻塞

**症状**:bot 跑几天后 event loop 卡住 / 内存爆。

**原因**:`on_message` handler 内阻塞 IO(`requests` / `time.sleep`),或协程未收集。

**修复**:
```python
import asyncio
import httpx
from wau_sdk.bot.telegram import Bot

# 1. handler 必须 async,非阻塞 IO 用 httpx(异步)
bot = Bot(token=token, tenant_id="tenant-A")

@bot.on_message
async def handle(msg):
    # ❌ 错:阻塞
    # import requests
    # requests.get("https://...")

    # ✅ 对:异步 httpx
    async with httpx.AsyncClient() as http:
        r = await http.get("https://...")
    return wau_sdk.bot.common.OutgoingMessage(text=r.text)

# 2. 收集 background task 防泄漏
pending = set()

@bot.on_message
async def handle(msg):
    task = asyncio.create_task(handle_async(msg))
    pending.add(task)
    task.add_done_callback(pending.discard)
    return wau_sdk.bot.common.OutgoingMessage(text="processing")

# 3. 测试:asyncio 任务前后对比
before = len(asyncio.all_tasks())
await bot.stop()
after = len(asyncio.all_tasks())
print(f"tasks before={before} after={after} (差应 <= 1)")
```

---

## 性能调优(预留,留给 v1.0.0 实测后)

> 本期(07-02)不写,留给 v1.0.0 实测后补。

- `httpx` 客户端连接池调优(`Limits(max_connections=100, max_keepalive_connections=20)`)
- TLS handshake 复用(`HTTPTransport(retries=3)`)
- 高并发下 `asyncio.Semaphore` 限流 + `dataclass(slots=True)` 减少内存
- 长 timeout 任务的 streaming(留 v1.2.0)

---

## 链接

- [README.md](./README.md) — 入口
- [API.md](./API.md) — 完整 API 参考
- [QUICKSTART.md](./QUICKSTART.md) — 15 分钟跑通
- [CHANGELOG.md](./CHANGELOG.md) — 版本变更
- [docs/auth.md](./docs/auth.md) — HS256 + JWT 详细
- [docs/retry_circuit.md](./docs/retry_circuit.md) — 重试 + 熔断详细
- [examples/](./examples/) — 7 个 runnable example

---

**维护**:Claude + youhaoxi(Stage 3.2 SDK doc 完整化,2026-07-02)
**WAU 业务代码改动 = 0**(纯文档,不改 .py)
