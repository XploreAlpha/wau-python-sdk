"""UCP commerce DTOs (wau-python-sdk v1.3.3, per D88.6).

8 commerce DTOs aligned byte-equal to:
  - kernel `internal/protocol/ucp/commerce_mock.go` shape
  - wau-go-sdk `ucpclient/types.go` (v1.3.3, cross-SDK D13 byte-equal)
  - design doc [[process/2026-07-11-W3-UCP-client-SDK-design]] §三

JSON field names use snake_case (per UCP spec + JSON-RPC 2.0 wire format).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Product:
    """DTO 1:商品 (对应 tool 1-3: list_products / get_product / search_products)"""

    product_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: int = 0
    currency: Optional[str] = None
    stock: int = 0
    images: list[str] = field(default_factory=list)
    category: Optional[str] = None
    created_at: Optional[str] = None
    available: Optional[bool] = None
    sku: Optional[str] = None


@dataclass
class ListProductsFilter:
    """list_products 可选过滤参数"""

    category: Optional[str] = None
    price_min_cents: int = 0
    price_max_cents: int = 0
    page: int = 0
    page_size: int = 0


@dataclass
class ListProductsResult:
    """DTO 2:list_products 返的 DTO"""

    products: list[Product] = field(default_factory=list)
    total: int = 0
    page: int = 0
    page_size: int = 0


@dataclass
class SearchProductsResult:
    """search_products 返的 DTO(简化版,无 page / page_size)"""

    products: list[Product] = field(default_factory=list)
    total: int = 0
    query: Optional[str] = None


@dataclass
class CartLineItem:
    """购物车单项(对应 tool 4-6)"""

    line_item_id: Optional[str] = None
    product_id: Optional[str] = None
    name: Optional[str] = None
    quantity: int = 0
    unit_price_cents: int = 0
    subtotal_cents: int = 0


@dataclass
class Cart:
    """DTO 3:购物车(add_to_cart / get_cart / remove_from_cart)

    必含 tenant_id 字段(per D65 multi-tenant)。
    """

    cart_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    line_items: list[CartLineItem] = field(default_factory=list)
    total_cents: int = 0
    currency: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    last_updated: Optional[str] = None
    removed: Optional[bool] = None  # remove_from_cart 特有


@dataclass
class CheckoutSession:
    """DTO 4:Stripe Checkout Session(create_checkout_session)

    W5+ Stripe 集成时,kernel 通过 /v1/ucp/webhooks/stripe 调 SDK,
    SDK 0 直接 Stripe(透明)。
    """

    checkout_session_id: Optional[str] = None
    cart_id: Optional[str] = None
    checkout_url: Optional[str] = None
    amount_cents: int = 0
    currency: Optional[str] = None
    status: Optional[str] = None  # "pending" / "completed" / "expired"
    expires_at: Optional[str] = None


@dataclass
class PaymentConfirmation:
    """DTO 5:Stripe payment_intent 确认(confirm_payment)"""

    checkout_session_id: Optional[str] = None
    payment_intent_id: Optional[str] = None
    status: Optional[str] = None  # "succeeded" / "failed" / "processing"
    order_id: Optional[str] = None


@dataclass
class Order:
    """DTO 6:订单(get_order / list_orders / cancel_order)

    必含 tenant_id 字段(per D65 multi-tenant)。
    """

    order_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[str] = None  # "pending" / "paid" / "shipped" / "delivered" / "canceled" / "refunded"
    line_items: list[CartLineItem] = field(default_factory=list)
    total_cents: int = 0
    currency: Optional[str] = None
    shipping_address: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ListOrdersFilter:
    """list_orders 可选过滤参数"""

    status: list[str] = field(default_factory=list)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    page: int = 0
    page_size: int = 0


@dataclass
class ListOrdersResult:
    """DTO 7:list_orders 返的 DTO"""

    orders: list[Order] = field(default_factory=list)
    total: int = 0
    page: int = 0
    page_size: int = 0


@dataclass
class CancelOrderResult:
    """DTO 8:cancel_order 返的 DTO(含 Stripe refund 流程)"""

    order_id: Optional[str] = None
    status: Optional[str] = None
    refund_id: Optional[str] = None
    refund_status: Optional[str] = None  # "pending" / "succeeded" / "failed"
    canceled_at: Optional[str] = None
    refund_reason: Optional[str] = None
