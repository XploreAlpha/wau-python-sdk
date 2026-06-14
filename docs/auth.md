# 鉴权(HS256 + JWT Bearer)

wau-python-sdk 支持可选的 HS256 JWT Bearer 鉴权(跟 wau-a2a-gateway 保持一致)。

## 启用鉴权

```python
import os
import wau_sdk
from wau_sdk import AuthConfig, Role

c = wau_sdk.Client(
    "http://localhost:18400",
    wau_sdk.ClientOptions(
        auth=AuthConfig(
            agent_name="my-agent",                       # 标识当前 agent
            shared_secret=os.environ["WAU_JWT_SECRET"].encode(),  # HS256 密钥
            role=Role.TRUSTED_AGENT,                     # RBAC
        ),
    ),
)
```

不传 `auth=...` = 不带鉴权(默认行为)。

## RBAC 角色

| Role | 权限 |
|---|---|
| `Role.KERNEL_CORE` | 全部(内部 kernel 用) |
| `Role.TRUSTED_AGENT` | Schedule + read-only(普通 agent) |
| `Role.EXTERNAL_AGENT`(默认) | Submit only(外部 SDK 用户) |

## JWT 结构

每个 HTTP 请求自动签一个新 JWT:

```json
{
  "agent": "my-agent",
  "role":  "trusted_agent",
  "iat":   1718342400,
  "exp":   1718342700,
  "jti":   "uuid-v4-string"
}
```

Header:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZ2VudCI6...
```

**安全参数**:
- **算法**: HS256(对称,密钥双方共享)
- **过期**: 5 分钟(短;每次请求新签,减小重放窗口)
- **jti**: UUID v4 防重放(可选:服务端可维护 jti 黑名单)

## 配置技巧

### 从环境变量读密钥(推荐)

```python
import os

secret = os.environ.get("WAU_JWT_SECRET")
if not secret:
    raise RuntimeError("WAU_JWT_SECRET 未设置")
c = wau_sdk.Client(
    "http://localhost:18400",
    wau_sdk.ClientOptions(
        auth=AuthConfig(
            agent_name="my-agent",
            shared_secret=secret.encode(),
        ),
    ),
)
```

### 自定义过期时间(高级)

```python
from wau_sdk._auth import Signer

signer = Signer(AuthConfig(agent_name="x", shared_secret=b"..."))
jwt = signer.sign(ttl_seconds=60)  # 1 分钟过期
```

### 异步用法一样

```python
async with wau_sdk.AsyncClient(
    "http://localhost:18400",
    wau_sdk.ClientOptions(
        auth=AuthConfig(agent_name="my-agent", shared_secret=b"..."),
    ),
) as c:
    resp = await c.tasks.submit(req)
```

## 不启用鉴权

```python
# 默认:不签 JWT
c = wau_sdk.Client("http://localhost:18400")
```

`Authorization` header 不会被设置。

## 错误处理

- `UnauthorizedError` (401): 密钥不对 / 过期 / jti 黑名单 → 检查 server 时间差 / 重新发 secret
- `ForbiddenError` (403): 角色不够 → 改 Role 或联系 server 提升权限

## 协议参考

JWT 实现用 [PyJWT](https://pyjwt.readthedocs.io/)(HS256 算法)。
Go SDK 用 [golang-jwt/jwt/v5](https://github.com/golang-jwt/jwt),TypeScript SDK 用 [jsonwebtoken](https://www.npmjs.com/package/jsonwebtoken),三语言行为完全对齐。
