# wau-python-sdk 15 分钟跑通

> 目标:pip install + 跑通 1 个 webhook bot。

## 前置

- Python 3.10+
- 上游:
  - **wau-llm-router** 在 :18404(直连模式)
  - 或 **wau-channel webhook** 在 :18431(SDK 模式)
- Telegram token:`$TELEGRAM_BOT_TOKEN`

## 步骤

### 1. 装 SDK

```bash
pip install wau-python-sdk==1.1.0
```

### 2. 5 行 bot

```python
# mybot.py
import os
from wau_python_sdk.bot.telegram import Bot

bot = Bot(
    token=os.environ["TELEGRAM_BOT_TOKEN"],
    tenant_id="acme",
)
bot.start()  # blocking
```

### 3. 跑

```bash
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN python mybot.py
```

预期:`[telegram-bot] listening, tenant=acme`

### 4. 触发 1 条消息

Telegram 私聊 bot 发 "hello",收到响应

## 直连模式

```python
from wau_python_sdk.client import Client

c = Client("127.0.0.1:18404")
resp = await c.resolve({"tenant_id": "acme", "intent": "chat"})
print(resp.model, resp.universe)
```

## 下一步

- [DEPLOY.md](DEPLOY.md) — PyPI 发布
- [ARCHITECTURE.md](ARCHITECTURE.md) — async/await 模型
- [README.md](README.md) — v0.9.0 收口段
