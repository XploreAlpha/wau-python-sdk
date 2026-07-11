"""UCP client (wau-python-sdk v1.3.3, per D88.6).

⭐ v1.0.0 D88.6 W3 + W5-W6 实装(2026-07-11)。

5 SDK 共享 wire format:JSON-RPC 2.0 over HTTP at POST {base_url}/ucp
(跟 WAU-core-kernel internal/protocol/ucp/server.go handleUCP 对齐)。

本模块 = 11 commerce tool wrapper (ListProducts / GetProduct / SearchProducts /
AddToCart / GetCart / RemoveFromCart / CreateCheckoutSession / ConfirmPayment /
GetOrder / ListOrders / CancelOrder) + JSON-RPC envelope + sync/async 双版本。

用法::

    sync:
        ucp = UCPClient("https://kernel.example.com", bearer_token="oauth-jwt")
        cart = ucp.add_to_cart("prod-123", 2)

    async:
        async with AsyncUCPClient("https://kernel.example.com", bearer_token=...) as ucp:
            cart = await ucp.add_to_cart("prod-123", 2)

协议合规:
  - D60 additive: 0 改老 SDK,新增独立子模块(跟 chat.py / bot/ 平级)
  - D13 byte-equal: JSON wire format 5 SDK 一致(per design doc §三)
  - D65 (tenant_id): Order / Cart DTO 含 tenant_id 字段
  - D66=B RBAC: owner_user_id 维持 string
  - D78/D79/D80: UCP OAuth 2.0 identity_linking bearer token(跟 MCP client 走同一通道)
  - D88 ⭐⭐: 本模块 = D88.6 Python SDK UCP client 实装(W3-launch-SOP §3.3 拍板)

设计原则:
  - httpx.Client/AsyncClient 由 caller 注入(测试用 MockTransport,生产用真 httpx)
  - 不引入 Pydantic,用 @dataclass(跟 wau_sdk.types.py 一致)
  - 错误统一抛 RPCError(JSON-RPC 2.0 envelope),跟 wau-go-sdk ucpclient.RPCError 字段对齐
  - Bearer token 走 OAuth 2.0 identity_linking(W3 stub;W5+ 加 refresh flow)
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Optional

import httpx

from wau_sdk.ucp_dto import (
    CancelOrderResult,
    Cart,
    CartLineItem,
    CheckoutSession,
    ListOrdersFilter,
    ListOrdersResult,
    ListProductsFilter,
    ListProductsResult,
    Order,
    PaymentConfirmation,
    Product,
    SearchProductsResult,
)
from wau_sdk.ucp_errors import (
    ERR_CODE_INTERNAL,
    RPCError,
)

__all__ = [
    "UCPClient",
    "AsyncUCPClient",
    "set_bearer_token",
    "set_tenant_id",
    "is_stripe_path",
]

_AUTH_HEADER = "Authorization"
_AUTH_SCHEME_PREFIX = "Bearer "
_TENANT_HEADER = "X-WAU-Tenant-ID"
_DEFAULT_USER_AGENT = "wau-python-sdk/ucp/v1.3.3"
_TOOLS_CALL = "tools/call"

# 11 commerce tool 命名常量(snake_case,对齐 kernel ucp/server.go ToolXxx + handler routeToCommerce)
TOOL_LIST_PRODUCTS = "list_products"
TOOL_GET_PRODUCT = "get_product"
TOOL_SEARCH_PRODUCTS = "search_products"
TOOL_ADD_TO_CART = "add_to_cart"
TOOL_GET_CART = "get_cart"
TOOL_REMOVE_FROM_CART = "remove_from_cart"
TOOL_CREATE_CHECKOUT_SESSION = "create_checkout_session"
TOOL_CONFIRM_PAYMENT = "confirm_payment"
TOOL_GET_ORDER = "get_order"
TOOL_LIST_ORDERS = "list_orders"
TOOL_CANCEL_ORDER = "cancel_order"

_STRIPE_PATH_TOOLS = frozenset(
    (TOOL_CREATE_CHECKOUT_SESSION, TOOL_CONFIRM_PAYMENT, TOOL_CANCEL_ORDER)
)


# ────────────────────────────────────────────────────────
# Auth helpers(跟 wau-go-sdk ucpclient/auth.go 字段对齐)
# ────────────────────────────────────────────────────────

def set_bearer_token(req: httpx.Request, token: str) -> None:
    """给现有 httpx.Request 注入 bearer token(per OAuth 2.0 / RFC 6750)。"""
    if token:
        req.headers[_AUTH_HEADER] = _AUTH_SCHEME_PREFIX + token


def set_tenant_id(req: httpx.Request, tenant_id: str) -> None:
    """给现有 httpx.Request 注入 tenant ID(per D65 multi-tenant)。

    W3 stub 阶段不传;W5+ 多租户切换时启用。
    """
    if tenant_id:
        req.headers[_TENANT_HEADER] = tenant_id


def is_stripe_path(tool_name: str) -> bool:
    """判断 tool name 是不是跟 Stripe 相关(create / confirm payment / cancel + refund)。"""
    return tool_name in _STRIPE_PATH_TOOLS


# ────────────────────────────────────────────────────────
# JSON-RPC envelope(sync + async 共用)
# ────────────────────────────────────────────────────────

_id_counter = itertools.count(1)


def _next_id() -> int:
    return next(_id_counter)


def _to_json_arguments(arguments: Any) -> Any:
    """把 dataclass / dict 转化为可 JSON 序列化的对象(JSON-RPC arguments 字段)。

    规则:None / [] / {} 视为 empty 跳过;0 视为 default 跳过(避免 polling 误传 default);
    嵌套 dataclass 字段递归转换(dacite-style)。
    """
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return {k: _to_json_arguments(v) for k, v in arguments.items() if v not in (None, [], {})}
    if is_dataclass(arguments):
        d = asdict(arguments)
        return {k: _to_json_arguments(v) for k, v in d.items() if v not in (None, [], {})}
    return arguments


def _handle_rpc_response(resp_json: dict) -> dict:
    """解析 JSON-RPC 2.0 Response envelope,err 抛 RPCError,成功返 result dict。"""
    if "error" in resp_json and resp_json["error"]:
        raise RPCError.from_dict(resp_json["error"])
    return resp_json.get("result") or {}


# ────────────────────────────────────────────────────────
# Sync UCPClient
# ────────────────────────────────────────────────────────

class UCPClient:
    """同步 UCP client。

    用法::

        ucp = UCPClient(
            base_url="https://kernel.example.com",
            bearer_token="oauth-jwt-xyz",
            http_client=httpx.Client(timeout=30.0),
        )
        try:
            cart = ucp.add_to_cart("prod-123", 2)
        finally:
            ucp.close()

        # 或者用 context manager(close 自动)
        with UCPClient(...) as ucp:
            ...

    11 commerce tool wrapper 共用 JSON-RPC 2.0 over HTTP transport。
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str = "",
        tenant_id: str = "",
        http_client: Optional[httpx.Client] = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        if not base_url:
            raise ValueError("ucp: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._bearer = bearer_token
        self._tenant = tenant_id
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=30.0)
        self._user_agent = user_agent

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "UCPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _build_request(self, tool_name: str, arguments: Any) -> httpx.Request:
        payload = {
            "jsonrpc": "2.0",
            "method": _TOOLS_CALL,
            "params": {"name": tool_name, "arguments": _to_json_arguments(arguments)},
            "id": _next_id(),
        }
        req = self._http.build_request(
            "POST",
            f"{self._base_url}/ucp",
            json=payload,
            headers={"User-Agent": self._user_agent},
        )
        set_bearer_token(req, self._bearer)
        set_tenant_id(req, self._tenant)
        return req

    def _call_tool(self, tool_name: str, arguments: Any) -> dict:
        req = self._build_request(tool_name, arguments)
        resp = self._http.send(req)
        if resp.status_code >= 400:
            raise RPCError(
                code=resp.status_code * -1,
                message=f"http {resp.status_code}: {resp.text}",
            )
        return _handle_rpc_response(resp.json())

    # ── 11 commerce tool wrapper ──────────────────────────

    def list_products(self, filter: Optional[ListProductsFilter] = None) -> ListProductsResult:
        result = self._call_tool(TOOL_LIST_PRODUCTS, filter)
        return ListProductsResult(
            products=[Product(**p) for p in result.get("products", [])],
            total=result.get("total", 0),
            page=result.get("page", 0),
            page_size=result.get("page_size", 0),
        )

    def get_product(self, product_id: str) -> Product:
        if not product_id:
            raise ValueError("ucp: product_id is required")
        result = self._call_tool(TOOL_GET_PRODUCT, {"product_id": product_id})
        return Product(**result)

    def search_products(self, query: str, limit: int = 10) -> SearchProductsResult:
        if not query:
            raise ValueError("ucp: query is required")
        args: dict[str, Any] = {"query": query}
        if limit > 0:
            args["limit"] = limit
        result = self._call_tool(TOOL_SEARCH_PRODUCTS, args)
        return SearchProductsResult(
            products=[Product(**p) for p in result.get("products", [])],
            total=result.get("total", 0),
            query=result.get("query"),
        )

    def add_to_cart(self, product_id: str, quantity: int = 1) -> Cart:
        if not product_id:
            raise ValueError("ucp: product_id is required")
        if quantity <= 0:
            quantity = 1
        result = self._call_tool(
            TOOL_ADD_TO_CART, {"product_id": product_id, "quantity": quantity}
        )
        return _cart_from_dict(result)

    def get_cart(self, cart_id: str) -> Cart:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        result = self._call_tool(TOOL_GET_CART, {"cart_id": cart_id})
        return _cart_from_dict(result)

    def remove_from_cart(self, cart_id: str, line_item_id: str) -> Cart:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        if not line_item_id:
            raise ValueError("ucp: line_item_id is required")
        result = self._call_tool(
            TOOL_REMOVE_FROM_CART,
            {"cart_id": cart_id, "line_item_id": line_item_id},
        )
        return _cart_from_dict(result)

    def create_checkout_session(self, cart_id: str) -> CheckoutSession:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        try:
            result = self._call_tool(TOOL_CREATE_CHECKOUT_SESSION, {"cart_id": cart_id})
        except RPCError as e:
            if e.code == ERR_CODE_INTERNAL and "W5" in e.message:
                raise NotImplementedError(
                    "ucp.create_checkout_session: W5 Stripe 集成中(D88.1 stub)"
                ) from e
            raise
        return CheckoutSession(**result)

    def confirm_payment(self, checkout_session_id: str) -> PaymentConfirmation:
        if not checkout_session_id:
            raise ValueError("ucp: checkout_session_id is required")
        try:
            result = self._call_tool(
                TOOL_CONFIRM_PAYMENT, {"checkout_session_id": checkout_session_id}
            )
        except RPCError as e:
            if e.code == ERR_CODE_INTERNAL and "W5" in e.message:
                raise NotImplementedError(
                    "ucp.confirm_payment: W5 Stripe 集成中(D88.1 stub)"
                ) from e
            raise
        return PaymentConfirmation(**result)

    def get_order(self, order_id: str) -> Order:
        if not order_id:
            raise ValueError("ucp: order_id is required")
        result = self._call_tool(TOOL_GET_ORDER, {"order_id": order_id})
        return Order(**result)

    def list_orders(
        self, user_id: str, filter: Optional[ListOrdersFilter] = None
    ) -> ListOrdersResult:
        if not user_id:
            raise ValueError("ucp: user_id is required")
        args: dict[str, Any] = {"user_id": user_id}
        if filter is not None:
            args["filter"] = filter
        result = self._call_tool(TOOL_LIST_ORDERS, args)
        return ListOrdersResult(
            orders=[Order(**o) for o in result.get("orders", [])],
            total=result.get("total", 0),
            page=result.get("page", 0),
            page_size=result.get("page_size", 0),
        )

    def cancel_order(self, order_id: str) -> CancelOrderResult:
        if not order_id:
            raise ValueError("ucp: order_id is required")
        result = self._call_tool(TOOL_CANCEL_ORDER, {"order_id": order_id})
        return CancelOrderResult(**result)


# ────────────────────────────────────────────────────────
# Async UCPClient(跟 sync 一对一)
# ────────────────────────────────────────────────────────

class AsyncUCPClient:
    """异步 UCP client。

    用法::

        async with AsyncUCPClient(
            "https://kernel.example.com",
            bearer_token="oauth-jwt",
        ) as ucp:
            cart = await ucp.add_to_cart("prod-123", 2)
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str = "",
        tenant_id: str = "",
        http_client: Optional[httpx.AsyncClient] = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        if not base_url:
            raise ValueError("ucp: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._bearer = bearer_token
        self._tenant = tenant_id
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=30.0)
        self._user_agent = user_agent

    @property
    def base_url(self) -> str:
        return self._base_url

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncUCPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _build_request(self, tool_name: str, arguments: Any) -> httpx.Request:
        payload = {
            "jsonrpc": "2.0",
            "method": _TOOLS_CALL,
            "params": {"name": tool_name, "arguments": _to_json_arguments(arguments)},
            "id": _next_id(),
        }
        req = self._http.build_request(
            "POST",
            f"{self._base_url}/ucp",
            json=payload,
            headers={"User-Agent": self._user_agent},
        )
        set_bearer_token(req, self._bearer)
        set_tenant_id(req, self._tenant)
        return req

    async def _call_tool(self, tool_name: str, arguments: Any) -> dict:
        req = self._build_request(tool_name, arguments)
        resp = await self._http.send(req)
        if resp.status_code >= 400:
            raise RPCError(
                code=resp.status_code * -1,
                message=f"http {resp.status_code}: {resp.text}",
            )
        return _handle_rpc_response(resp.json())

    async def list_products(
        self, filter: Optional[ListProductsFilter] = None
    ) -> ListProductsResult:
        result = await self._call_tool(TOOL_LIST_PRODUCTS, filter)
        return ListProductsResult(
            products=[Product(**p) for p in result.get("products", [])],
            total=result.get("total", 0),
            page=result.get("page", 0),
            page_size=result.get("page_size", 0),
        )

    async def get_product(self, product_id: str) -> Product:
        if not product_id:
            raise ValueError("ucp: product_id is required")
        result = await self._call_tool(TOOL_GET_PRODUCT, {"product_id": product_id})
        return Product(**result)

    async def search_products(self, query: str, limit: int = 10) -> SearchProductsResult:
        if not query:
            raise ValueError("ucp: query is required")
        args: dict[str, Any] = {"query": query}
        if limit > 0:
            args["limit"] = limit
        result = await self._call_tool(TOOL_SEARCH_PRODUCTS, args)
        return SearchProductsResult(
            products=[Product(**p) for p in result.get("products", [])],
            total=result.get("total", 0),
            query=result.get("query"),
        )

    async def add_to_cart(self, product_id: str, quantity: int = 1) -> Cart:
        if not product_id:
            raise ValueError("ucp: product_id is required")
        if quantity <= 0:
            quantity = 1
        result = await self._call_tool(
            TOOL_ADD_TO_CART, {"product_id": product_id, "quantity": quantity}
        )
        return _cart_from_dict(result)

    async def get_cart(self, cart_id: str) -> Cart:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        result = await self._call_tool(TOOL_GET_CART, {"cart_id": cart_id})
        return _cart_from_dict(result)

    async def remove_from_cart(self, cart_id: str, line_item_id: str) -> Cart:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        if not line_item_id:
            raise ValueError("ucp: line_item_id is required")
        result = await self._call_tool(
            TOOL_REMOVE_FROM_CART,
            {"cart_id": cart_id, "line_item_id": line_item_id},
        )
        return _cart_from_dict(result)

    async def create_checkout_session(self, cart_id: str) -> CheckoutSession:
        if not cart_id:
            raise ValueError("ucp: cart_id is required")
        try:
            result = await self._call_tool(
                TOOL_CREATE_CHECKOUT_SESSION, {"cart_id": cart_id}
            )
        except RPCError as e:
            if e.code == ERR_CODE_INTERNAL and "W5" in e.message:
                raise NotImplementedError(
                    "ucp.create_checkout_session: W5 Stripe 集成中(D88.1 stub)"
                ) from e
            raise
        return CheckoutSession(**result)

    async def confirm_payment(self, checkout_session_id: str) -> PaymentConfirmation:
        if not checkout_session_id:
            raise ValueError("ucp: checkout_session_id is required")
        try:
            result = await self._call_tool(
                TOOL_CONFIRM_PAYMENT, {"checkout_session_id": checkout_session_id}
            )
        except RPCError as e:
            if e.code == ERR_CODE_INTERNAL and "W5" in e.message:
                raise NotImplementedError(
                    "ucp.confirm_payment: W5 Stripe 集成中(D88.1 stub)"
                ) from e
            raise
        return PaymentConfirmation(**result)

    async def get_order(self, order_id: str) -> Order:
        if not order_id:
            raise ValueError("ucp: order_id is required")
        result = await self._call_tool(TOOL_GET_ORDER, {"order_id": order_id})
        return Order(**result)

    async def list_orders(
        self, user_id: str, filter: Optional[ListOrdersFilter] = None
    ) -> ListOrdersResult:
        if not user_id:
            raise ValueError("ucp: user_id is required")
        args: dict[str, Any] = {"user_id": user_id}
        if filter is not None:
            args["filter"] = filter
        result = await self._call_tool(TOOL_LIST_ORDERS, args)
        return ListOrdersResult(
            orders=[Order(**o) for o in result.get("orders", [])],
            total=result.get("total", 0),
            page=result.get("page", 0),
            page_size=result.get("page_size", 0),
        )

    async def cancel_order(self, order_id: str) -> CancelOrderResult:
        if not order_id:
            raise ValueError("ucp: order_id is required")
        result = await self._call_tool(TOOL_CANCEL_ORDER, {"order_id": order_id})
        return CancelOrderResult(**result)


# ────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────

def _cart_from_dict(d: dict) -> Cart:
    """把 raw result dict 转 Cart(嵌套 line_items 也解析)。"""
    line_items = [
        CartLineItem(**li) for li in d.get("line_items", []) or []
    ]
    return Cart(
        cart_id=d.get("cart_id"),
        user_id=d.get("user_id"),
        tenant_id=d.get("tenant_id"),
        line_items=line_items,
        total_cents=d.get("total_cents", 0),
        currency=d.get("currency"),
        created_at=d.get("created_at"),
        expires_at=d.get("expires_at"),
        last_updated=d.get("last_updated"),
        removed=d.get("removed"),
    )
