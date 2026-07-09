"""bot.common.account — Account / BotRegistry 公共 DTO(per M10 / D82=A)

公开 bot id 格式:"bot:<tenant>:<botid>"
例:tenant=acme, botID=weather-cn → public_bot_id="bot:acme:weather-cn"

4 SDK 必须保持字段名 + 类型 100% 一致(per D13 拍板)。
wau-go-sdk/bot/common/account.go
wau-typescript-sdk/src/bot/common/account.ts
wau-rust-sdk/src/bot/common/account.rs
必须随时保持同步,字段一字不差。

v1.3.0 (W7.1, 2026-07-09) — 新加 bot_uuid (UUID v4, server-assigned)
per D78/D79/D80 拍板;D60 additive,0 改老字段。老 bot_id slug 语义不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def public_bot_id_of(tenant_id: str, bot_id: str) -> str:
    """纯函数:tenant + bot → public_bot_id

    等价于 f"bot:{tenant_id}:{bot_id}"。SDK 任何需要派生公开 ID 的地方
    走这个 helper,避免散落 f-string。
    """
    return f"bot:{tenant_id}:{bot_id}"


@dataclass
class Account:
    """B 端注册的 bot 账户(per M10 N1 / D82=A 拍板)。

    注:此 Account 是 bot 注册中心(wau-registry-service)入口的领域对象,
    不是 wau-store 的 Account(财务账户),两者不应混用。
    """

    # server-assigned UUID (空 = 待注册)
    account_id: str = ""

    # 多租户 ID(必填,例 "acme")
    tenant_id: str = ""

    # 本地名 / slug(必填,例 "weather-cn"),tenant 内唯一
    bot_id: str = ""

    # 服务端分配的 UUID v4(per D78,per tenant 全局唯一)。
    # 与 bot_id slug 不同:bot_id = human-readable client-supplied,bot_uuid = machine-friendly server-assigned。
    # 用途:wau-edge route 寻址 / wau-channel 8 平台 adapter 寻址 / D79 JWT 4 claims 之一。
    # Register 响应返回(服务端决定,不接受 client 上传)。空 = 老 SDK v1.2.0 兼容降级路径。
    bot_uuid: str = ""

    # 全局公开 ID = bot:<tenant>:<botid>(D82=A 服务端回填校验)
    public_bot_id: str = ""

    # 注册人 user_id(C 端 或 B 端 owner)
    owner_user_id: str = ""

    # IM 平台类型:"telegram"|"discord"|"slack"|"feishu"|"dingtalk"|"qq"|"email"|"webhook"
    channel_type: str = ""

    # wau-channel 内的 config ID(platform credentials 索引)
    channel_config_id: str = ""

    # UTC timestamp(服务端回填,客户端只读)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def new_account(
    tenant_id: str,
    bot_id: str,
    owner_user_id: str,
    channel_type: str,
    channel_config_id: str,
) -> Account:
    """构造 Account 并填充 public_bot_id + created_at/updated_at(D82=A)。

    account_id 留空 → 服务端 Register 时回填。
    """
    now = _utcnow()
    return Account(
        tenant_id=tenant_id,
        bot_id=bot_id,
        public_bot_id=public_bot_id_of(tenant_id, bot_id),
        owner_user_id=owner_user_id,
        channel_type=channel_type,
        channel_config_id=channel_config_id,
        created_at=now,
        updated_at=now,
    )


@dataclass
class RegisterBotRequest:
    """B 端注册 bot 请求体(POST /registry/bots)。

    与 Account 区别:不带 account_id / created_at / updated_at
    (这些是服务端回填的字段)。

    v1.3.0 (W7.1, D78) — 新增 bot_uuid 字段(可选,server-assigned,
    不传 = 老 SDK v1.2.0 兼容路径,server 自动从 bot_id slug 寻址并生成)。
    """
    tenant_id: str = ""
    bot_id: str = ""
    bot_uuid: str = ""
    owner_user_id: str = ""
    channel_type: str = ""
    channel_config_id: str = ""


@dataclass
class UpdateBotRequest:
    """B 端更新 bot 请求体(PUT /registry/bots/{public_bot_id})。

    只允许改 owner_user_id / channel_type / channel_config_id。
    tenant_id / bot_id / public_bot_id 都是 immutable。
    """
    owner_user_id: str = ""
    channel_type: str = ""
    channel_config_id: str = ""


@dataclass
class ListBotsFilter:
    """列举 bot 时的过滤条件(GET /registry/bots)"""
    tenant_id: str = ""
    owner_user_id: str = ""
    channel_type: str = ""
    limit: int = 0
