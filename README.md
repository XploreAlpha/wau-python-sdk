# wau-python-sdk

> **WAU Python SDK v1.0.0 GA** — 官方 Python 客户端,WAU-core-kernel 智能调度内核接入入口
> v0.7.0 "Amber" 🔷 — **v1.0.0 = 2026-06-19 GA**(M3 W6 完成,2026-07-25 W7.7 文档校准)

[![PyPI](https://badge.fury.io/py/wau-sdk.svg)](https://pypi.org/project/wau-sdk/)
[![Version](https://img.shields.io/badge/version-v1.0.0-blue?style=flat-square)](https://pypi.org/project/wau-sdk/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

## 状态

✅ **v1.0.0 GA** (2026-06-19 → 2026-07-25 W7.7 文档校准) — **Public API stable**

| 阶段 | 估时(plan §5.5) | 实际 | 状态 |
|---|---|---|---|
| W6.7 脚手架 (pyproject + 6 源文件) | 0.5 d | ~0.3 d | ✅ |
| W6.8 翻译 wau-circuit (154 行 Go → ~150 行 Python) | 0.5 d | ~0.3 d | ✅ |
| W6.9 Client + AsyncClient + 4 服务 + 装饰器链 | 2 d | ~0.4 d | ✅ |
| W6.10 测试 (95 单测 + 5 场景契约 + 88% 覆盖率) | 1 d | ~0.5 d | ✅ |
| W6.10-3 CI workflow (pytest + ruff + mypy + coverage) | 0.5 d | ~0.1 d | ✅ |
| W6.11 docs (4 文档) + 4 examples | 0.5 d | ~0.1 d | ✅ |
| W7.7 Public API stable + deprecation policy 文档校准 | 0.05 d | ~0.05 d | ✅ |
| tag v1.0.0 + 发 PyPI | 0.5 d | ⏳ 用户手动(已 tag,发包待你) |

**实际完成 ~1.7d(估时 5d,提前 3.3d)**

## 安装

```bash
pip install wau-sdk==1.0.0
```

## 5 分钟快速开始

```python
import wau_sdk

with wau_sdk.Client("http://localhost:18400") as c:
    resp = c.tasks.submit(wau_sdk.SubmitRequest(
        prompt="What is the capital of France?",
        timeout_ms=30000,
    ))
    print(f"✅ {resp.selected_agent}: {resp.response}")
```

异步用法:
```python
import asyncio
import wau_sdk

async def main():
    async with wau_sdk.AsyncClient("http://localhost:18400") as c:
        resp = await c.tasks.submit(wau_sdk.SubmitRequest(
            prompt="What is the capital of France?",
        ))
        print(f"✅ {resp.selected_agent}: {resp.response}")

asyncio.run(main())
```

## 核心特性

- **11 HTTP 端点 × 2 同步/异步** = 22 方法
- **typed errors**:`*APIError` + 6 个 4xx 子类 + `CircuitOpenError` + `MaxRetriesError`
- **重试**:指数退避 + 抖动(tenacity),默认 3 次 / 200ms-5s
- **熔断**:集成 wau-circuit(154 行 Go → ~150 行 Python),3 SDK 行为字节级一致
- **HS256 鉴权**:JWT Bearer,5min exp,UUID v4 jti 防重放
- **gRPC stub**:`IntentService` 4 方法返 `NotImplementedError`(P2 推 M3.1)
- **5 场景契约**:与 [wau-go-sdk](https://github.com/XploreAlpha/wau-go-sdk) 共享同一份黄金 JSON,3 SDK 行为对齐

## 测试

```bash
# 全部测试(95 passed in ~3s)
pytest -v

# 带覆盖率
pytest --cov=wau_sdk --cov-report=term

# 5 场景契约
pytest -m contract
```

**当前覆盖率: 88%**(超过 plan §10.2 80% 门槛)

## 关联仓库

- 上游: [wau-core-kernel](https://github.com/XploreAlpha/WAU-core-kernel) (HTTP :18400, gRPC :50051)
- 兄弟: [wau-go-sdk](https://github.com/XploreAlpha/wau-go-sdk) | [wau-typescript-sdk](https://github.com/XploreAlpha/wau-typescript-sdk) (W6.5-W7)
- 依赖: [wau-circuit](https://github.com/XploreAlpha/wau-circuit) (熔断器,Python 翻译版)
- 共享契约: [wau-go-sdk/tests/contract-golden/](https://github.com/XploreAlpha/wau-go-sdk/tree/main/tests/contract-golden) (5 黄金 JSON)

## 计划文档

- [M3 W6 进度报告](/home/inamoto888/WAU-develop/develop-log/kernel/v0.6.0/2026-06-14-M3-W6.7-10.1-wau-python-sdk-progress.md)
- [M3 计划](/home/inamoto888/.claude/plans/lexical-orbiting-nova.md)
- [wau-go-sdk 架构决策 (ADR-0001~0004)](https://github.com/XploreAlpha/wau-go-sdk/tree/main/docs/adr)

## v0.9.0 "Acorn" 收口段(2026-09-15 GA)

上文介绍 v0.7.0 计划 + ADR 链接。本段为 v0.9.0 GA 增量补充。

### 角色

| OS 类比 | Client SDK(Python,开发者入口)|
|---|---|
| 部署 | Python package,PyPI 发布 |
| 通信 | gRPC → wau-llm-router :18404 + wau-channel webhook |
| 状态 | v1.1.0 同步发版(2026-07-13)|

### v0.9.0 新增

- **直连 wau-llm-router**(per [[project-v0-9-0-M3-§3.7-chat-sdk-4langs-2026-06-30]])
- **bot/ 字段 5/5 对齐 4 SDK**(per [[project-v0-9-0-stage0-closure-2026-06-28]])
- **Python 风格 API**:async / await + dict 类型友好

### 5 行 Python bot

```python
import os
from wau_python_sdk.bot.telegram import Bot

bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"], tenant_id="acme")
bot.start()  # blocking
```

### v0.9.0 "Acorn" 5 份核心文档

| # | 文件 | 内容 |
|---|---|---|
| 1 | [README.md](README.md)(本文件)| SDK 入口 |
| 2 | [QUICKSTART.md](QUICKSTART.md) | 15 分钟跑通 bot |
| 3 | [DEPLOY.md](DEPLOY.md) | PyPI 发布 |
| 4 | [ARCHITECTURE.md](ARCHITECTURE.md) | 模块 + 4 SDK 对齐 |
| 5 | [CHANGELOG.md](CHANGELOG.md) | v0.7.0 + v1.1.0 倒序(114 行已存在)|

### 历史锚点

- v1.1.0 SDK 同步发版(per [[project-v0.8.0-GA-2026-07-13]])
- 4 SDK 一致(per [[project-v0-9-0-M3-§3.7-chat-sdk-4langs-2026-06-30]])

## 协议

MIT © 2026 youhaoxi
## Bot Platforms

WAU SDK 通过两段责任分工对接 N 个 Bot 平台:

| 责任段 | 仓 | 文件 | 覆盖范围 |
|---|---|---|---|
| **公共契约** | 本 SDK(`bot/common/bots_service.<ext>`) | `Bot` + `BotsService` 抽象接口 | 5 SDK 100% 一致(per M10 N1)|
| **C 端 SDK bot/ 子包** | 本 SDK | `bot/{telegram,discord,webhook,slack,feishu,qq,dingtalk,email}/` | 每个 SDK 自带 8 平台(W5 Q1=B 反 W4.1 拍板)|
| **服务端 8 平台 adapter** | `wau-channel` | `internal/adapter/{slack,feishu,dingtalk,qq,email,telegram,discord,webhook}/*_real.go` | 全部 8 平台完整 4 步(per W7 2026-07-07 SDK 接通)|
| **服务端 bot HTTP API** | `wau-edge` | `POST /v1/bots/{bot_id}/messages`(per M10 N3) | Bot → 后端路由 |

**Bot Platforms 公开能力表**(2026-07-13, **W5 update 反 W4.1**):

| Platform     | 本 SDK bot/ | wau-channel adapter | 状态 |
|--------------|-------------|---------------------|------|
| Telegram     | ✅ | ✅ | 双端完整 |
| Discord      | ✅ | ✅ | 双端完整 |
| Webhook      | ✅ | ✅ | 双端完整 |
| Slack        | ✅ Stage 0 | ✅ 完整 4 步(`slack-go/slack` v0.27+) | W5 Stage 0 stub, Stage 1 待补 |
| Feishu       | ✅ Stage 0 | ✅ 完整 4 步(`lark-oapi` v3) | W5 Stage 0 stub, Stage 1 待补 |
| QQ           | ✅ Stage 0 | ✅ 完整 4 步(`tencent-connect/botgo`) | W5 Stage 0 stub, Stage 1 待补 |
| DingTalk     | ✅ Stage 0 | ✅ 完整 4 步(`dingtalk-stream-sdk`) | W5 Stage 0 stub, Stage 1 待补 |
| Email        | ✅ Stage 0 | ✅ 完整 4 步(`go-imap v1` + `net/smtp`) | W5 Stage 0 stub, Stage 1 待补 |

> **W5 反 W4.1 设计反转**(per 2026-07-13 Q1=B 拍板):SDK 端 bot/ 现已支持 8 平台(原 W4.1 仅 3 平台);5 平台 (Slack/Feishu/QQ/DingTalk/Email) 走 SDK 端 Stage 0 stub 替代原"⛔ 走服务端 adapter"。Stage 1 路径(per M11 W5-W6)将替换 stub 为 native SDK integration。W7 之后 wau-channel 8 平台 adapter 全部完整(per W7 2026-07-07 SDK 接通)。

**使用范式**(4 SDK 一致,Go SDK 示例):

```go
// SDK 端(B 端开发者):通过 BotsService 公共契约操作 bot
client.Bots().Register(ctx, wau.RegisterBotRequest{
    TenantID:     "acme",
    Universe:     "default",
    PublicBotID:  "weather-bot",
})

// 平台通信端:平台 SDK 自动选择 — 通过 wau-channel 服务端 adapter 调用
// SDK 不需要直接 import slack/feishu/... — 走 wau-channel HTTP API
```

> **本节由 W4.1 README 标准化自动 append,2026-07-13**。D60 additive:0 改 README 老内容。
>
> 关联:`WAU-develop/develop-log/kernel/v1.0.0/stage2/2026-07-13-PROGRESS-W4-launch.md`
