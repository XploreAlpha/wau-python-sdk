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

## 协议

MIT © 2026 youhaoxi
