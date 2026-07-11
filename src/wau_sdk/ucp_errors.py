"""UCP RPC error types (wau-python-sdk v1.3.3, per D88.6).

跟 wau-go-sdk `ucpclient/errors.go` 字段 1:1 对齐 (cross-SDK D13 byte-equal)。
JSON-RPC 2.0 spec 5 code + 5 UCP-specific code (-32101 ~ -32105)。
"""

from __future__ import annotations

from typing import Any, Optional


class RPCError(Exception):
    """JSON-RPC 2.0 error object 的 Python 表达(per spec + UCP 扩展)。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(self._format())

    def _format(self) -> str:
        return f"ucp rpc error: code={self.code} message={self.message!r}"

    @classmethod
    def from_dict(cls, d: dict) -> "RPCError":
        return cls(
            code=int(d.get("code", -32603)),
            message=str(d.get("message", "")),
            data=d.get("data"),
        )


# ────────────────────────────────────────────────────────
# JSON-RPC 2.0 spec error codes(跟 kernel ucp.ErrCode* 一致)
# ────────────────────────────────────────────────────────

ERR_CODE_PARSE = -32700
ERR_CODE_INVALID_REQUEST = -32600
ERR_CODE_METHOD_NOT_FOUND = -32601
ERR_CODE_INVALID_PARAMS = -32602
ERR_CODE_INTERNAL = -32603

# UCP-specific(-32100 ~ -32199,跟 MCP -32001 ~ -32003 错开)
ERR_CODE_UCP_PRODUCT_NOT_FOUND = -32101
ERR_CODE_UCP_CART_EXPIRED = -32102
ERR_CODE_UCP_STRIPE_ERROR = -32103
ERR_CODE_UCP_ORDER_NOT_FOUND = -32104
ERR_CODE_UCP_PAYMENT_FAILED = -32105


def is_not_found(err: BaseException) -> bool:
    """判断 err 是不是 product / order / cart 'not found' 语义错误(UCP spec)。"""
    if isinstance(err, RPCError):
        return err.code in (ERR_CODE_UCP_PRODUCT_NOT_FOUND, ERR_CODE_UCP_ORDER_NOT_FOUND)
    return False


def is_stripe_error(err: BaseException) -> bool:
    """判断 err 是不是 Stripe API 路径错误。"""
    if isinstance(err, RPCError):
        return err.code in (ERR_CODE_UCP_STRIPE_ERROR, ERR_CODE_UCP_PAYMENT_FAILED)
    return False
