"""UCP Stripe helpers (wau-python-sdk v1.3.3, per D88.6).

SDK 0 直接依赖 stripe — 所有 Stripe API call 都由 kernel
internal/protocol/ucp/ucp_stripe.go(W5+)转发,SDK 只发常规 HTTP/JSON-RPC。
本模块只是 helper 集合(W3 stub 阶段)。
"""

from __future__ import annotations

# Stripe path 判断(tool name 层面)
from wau_sdk.ucp_client import (
    is_stripe_path,
    TOOL_CREATE_CHECKOUT_SESSION,
    TOOL_CONFIRM_PAYMENT,
    TOOL_CANCEL_ORDER,
)

# Payment status 标准常量(per design doc §三.2.2 DTO 5 PaymentConfirmation.status)
PAYMENT_STATUS_SUCCEEDED = "succeeded"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_PROCESSING = "processing"
PAYMENT_STATUS_PENDING = "pending"


__all__ = [
    "is_stripe_path",
    "PAYMENT_STATUS_SUCCEEDED",
    "PAYMENT_STATUS_FAILED",
    "PAYMENT_STATUS_PROCESSING",
    "PAYMENT_STATUS_PENDING",
    "TOOL_CREATE_CHECKOUT_SESSION",
    "TOOL_CONFIRM_PAYMENT",
    "TOOL_CANCEL_ORDER",
]
