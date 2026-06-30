# wau-python-sdk 架构

## 模块拆分

```
wau-python-sdk/
├── wau_python_sdk/
│   ├── __init__.py
│   ├── client.py               # async gRPC → wau-llm-router
│   ├── bot/
│   │   ├── adapter.py          # BotAdapter 基类
│   │   ├── telegram/           # Telegram adapter
│   │   ├── discord/            # Discord adapter
│   │   └── webhook/            # Webhook adapter
├── examples/
│   └── bot_webhook.py          # 5 行 bot 例子
├── tests/
├── pyproject.toml
└── README.md / QUICKSTART.md / DEPLOY.md / ARCHITECTURE.md / CHANGELOG.md
```

## 数据流(同 Go SDK,Python 风格)

### SDK 模式

```python
bot.start() → asyncio loop
    ↓ Telegram 长拉
telegram.Bot(token)
    ↓ 转 A2A Task
wau-channel webhook :18431
    ↓ → wau-core-kernel → wau-llm-router → LLM
    ↓ 响应
Python await → bot.send_message(...)
```

### 直连模式(async)

```python
async with Client("127.0.0.1:18404") as c:
    resp = await c.resolve({"tenant_id": "acme", "intent": "chat"})
```

## 关键决策

| 决策 | 内容 |
|---|---|
| **async / await 一等公民** | Pythonic 风格 |
| **bot/ 字段 5/5 对齐** | per [[project-v0-9-0-stage0-closure-2026-06-28]] |
| **26 funcs / 0 回归** | per [[project-v0-9-0-M3-§3.7-chat-sdk-4langs-2026-06-30]] |

## 接口边界

- **入**:B 端 Python app
- **出**:bot 启动 / async Resolve response
- **依赖**:wau-channel / wau-llm-router
- **被依赖**:B 端 app

## 性能预算

| 指标 | 目标 |
|---|---|
| Resolve P50(async) | < 1 ms |
| Bot 启动 | < 200 ms |
| 消息处理 | < 100 ms |

## 跟其他仓的关系

- **上游**:B 端 app
- **下游**:wau-channel / wau-llm-router
- **同组 SDK(per [[project-v0-9-0-stage0-closure-2026-06-28]])**:wau-go-sdk / wau-typescript-sdk / wau-rust-sdk
