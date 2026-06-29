"""bot.common.message — 4 SDK 共享消息类型(per D13 拍板:字段名 + 类型 100% 一致)

字段定义严格对齐 wau-go-sdk/bot/common/message.go:

    IncomingMessage   — 收到用户消息
    OutgoingMessage   — 发送给用户消息
    Attachment        — 通用附件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    """UTC timezone-aware now(替代已废弃的 datetime.utcnow())"""
    return datetime.now(timezone.utc)


@dataclass
class Attachment:
    """通用附件(per D13 Attachment.Type 取值 "image"/"file"/"audio"/"video")

    对齐 wau-go-sdk/bot/common/message.go:28-32 Attachment。
    """
    type: str = ""
    url: str = ""
    name: str = ""


@dataclass
class IncomingMessage:
    """收到用户消息(per D13 与 wau-channel/adapter/adapter.go 对齐)

    对齐 wau-go-sdk/bot/common/message.go:9-18 IncomingMessage。
    """
    platform_msg_id: str = ""
    channel_id: str = ""
    user_id: str = ""
    username: str = ""
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    reply_to: str = ""
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class OutgoingMessage:
    """发送给用户消息

    对齐 wau-go-sdk/bot/common/message.go:21-25 OutgoingMessage。
    """
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    reply_to: str = ""
