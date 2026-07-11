"""MCP RPC error types (wau-python-sdk v1.3.2, per D87.6).

跟 wau-go-sdk `mcpclient/errors.go` 字段 1:1 对齐 (cross-SDK D13 byte-equal)。
JSON-RPC 2.0 spec 5 code + 3 MCP-specific code (-32001 ~ -32003,跟 UCP -32101 ~ -32105 错开)。
"""

from __future__ import annotations

from typing import Any


class RPCError(Exception):
    """JSON-RPC 2.0 error object 的 Python 表达(per spec + MCP 扩展)。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(self._format())

    def _format(self) -> str:
        return f"mcp rpc error: code={self.code} message={self.message!r}"

    @classmethod
    def from_dict(cls, d: dict) -> "RPCError":
        return cls(
            code=int(d.get("code", -32603)),
            message=str(d.get("message", "")),
            data=d.get("data"),
        )


# ────────────────────────────────────────────────────────
# JSON-RPC 2.0 spec error codes(跟 kernel mcp.ErrCode* 一致)
# ────────────────────────────────────────────────────────

ERR_CODE_PARSE = -32700
ERR_CODE_INVALID_REQUEST = -32600
ERR_CODE_METHOD_NOT_FOUND = -32601
ERR_CODE_INVALID_PARAMS = -32602
ERR_CODE_INTERNAL = -32603

# MCP-specific(-32001 ~ -32003,跟 UCP -32101 ~ -32105 错开)
ERR_CODE_MCP_AGENT_UNREACHABLE = -32001
ERR_CODE_MCP_INVALID_AGENT_CARD = -32002
ERR_CODE_MCP_TASK_NOT_FOUND = -32003


def is_agent_unreachable(err: BaseException) -> bool:
    """判断 err 是不是 agent unreachable 语义错误(MCP spec)。"""
    if isinstance(err, RPCError):
        return err.code == ERR_CODE_MCP_AGENT_UNREACHABLE
    return False


def is_task_not_found(err: BaseException) -> bool:
    """判断 err 是不是 task 'not found' 语义错误(MCP spec)。"""
    if isinstance(err, RPCError):
        return err.code == ERR_CODE_MCP_TASK_NOT_FOUND
    return False