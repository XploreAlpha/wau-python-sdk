"""bot.common.bots_service — BotsService 公共 ABC(per M10 N1 / D82=A)

4 SDK 必须保持签名 100% 一致(per D13):
  - register(req) -> Account
  - get(public_bot_id) -> Account
  - update(public_bot_id, req) -> Account
  - list(filter) -> list[Account]
  - delete(public_bot_id) -> None
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from wau_sdk.bot.common.account import (
    Account,
    ListBotsFilter,
    RegisterBotRequest,
    UpdateBotRequest,
)


class BotsService(ABC):
    """M10 bot 注册中心客户端接口(per D13:4 SDK 必须保持签名一致)。

    调用方:B 端 SDK 上架工具(wau-cli)、wau-edge 路由层、wau-agent 启动时拉取 bot 列表。
    实现方:每个 SDK 的 `bot/registry/` 子包,通常走 HTTP POST /registry/bots。

    错误语义(per D60):
      - bot 不存在:get/update/delete 返 BotNotFoundError
      - 冲突(register):返 BotAlreadyExistsError
      - 参数错误:返 ValueError / TypeError(wrapped)
    """

    @abstractmethod
    def register(self, req: RegisterBotRequest) -> Account:
        """注册新 bot。服务端分配 account_id + timestamps,客户端不传。

        Raises:
            BotAlreadyExistsError: tenant_id + bot_id 已存在
            ValueError: 参数缺失
        """

    @abstractmethod
    def get(self, public_bot_id: str) -> Account:
        """按公开 ID 获取 bot 信息。

        Raises:
            BotNotFoundError: bot 不存在
        """

    @abstractmethod
    def update(self, public_bot_id: str, req: UpdateBotRequest) -> Account:
        """更新 bot 可变字段(owner_user_id / channel_type / channel_config_id)。

        Raises:
            BotNotFoundError: bot 不存在
        """

    @abstractmethod
    def list(self, filter: ListBotsFilter) -> List[Account]:
        """按 filter 列出 bot 信息(per B 端 RBAC 过滤)。"""

    @abstractmethod
    def delete(self, public_bot_id: str) -> None:
        """按公开 ID 注销 bot。

        Raises:
            BotNotFoundError: bot 不存在
        """


# 公共 sentinel errors(实现方 wrap 时保留类型)
class BotNotFoundError(Exception):
    """bot 不存在(Get/Update/Delete 时)"""


class BotAlreadyExistsError(Exception):
    """注册冲突(tenant_id + bot_id 已存在)"""
