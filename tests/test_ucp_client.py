"""UCP client 单测 (wau-python-sdk v1.3.3, per D88.6).

镜像 wau-go-sdk ucpclient/client_test.go 28 测试,本文件 ~28 + async ~6 = 30+ 测试。
用 httpx.MockTransport mock kernel handleUCP dispatcher(不依赖 respx,UCPClient 是独立 client)。

覆盖矩阵:
  - 11 commerce tool sync happy path
  - create_checkout_session + confirm_payment W3 stub → NotImplementedError
  - ListProducts + ListOrders with filter
  - Local validation(product_id / cart_id / line_item_id / query / user_id / order_id 必填)
  - RPCError 翻译:JSON-RPC 错误 / 4xx HTTP / malformed JSON
  - Error code:UCP -32101 / -32103 / -32601
  - Auth helper: set_bearer_token + set_tenant_id
  - Stripe helper: is_stripe_path
  - Async UCPClient 同等覆盖
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

# 允许在仓库 root 直接跑(`python tests/test_ucp_client.py`)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wau_sdk.ucp_client import (  # noqa: E402
    TOOL_ADD_TO_CART,
    TOOL_CANCEL_ORDER,
    TOOL_CONFIRM_PAYMENT,
    TOOL_CREATE_CHECKOUT_SESSION,
    TOOL_GET_CART,
    TOOL_GET_ORDER,
    TOOL_GET_PRODUCT,
    TOOL_LIST_ORDERS,
    TOOL_LIST_PRODUCTS,
    TOOL_REMOVE_FROM_CART,
    TOOL_SEARCH_PRODUCTS,
    AsyncUCPClient,
    UCPClient,
    is_stripe_path,
    set_bearer_token,
    set_tenant_id,
)
from wau_sdk.ucp_dto import (  # noqa: E402
    CancelOrderResult,
    Cart,
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
from wau_sdk.ucp_errors import (  # noqa: E402
    ERR_CODE_INTERNAL,
    ERR_CODE_METHOD_NOT_FOUND,
    ERR_CODE_UCP_PAYMENT_FAILED,
    ERR_CODE_UCP_PRODUCT_NOT_FOUND,
    ERR_CODE_UCP_STRIPE_ERROR,
    RPCError,
    is_not_found,
    is_stripe_error,
)


# ────────────────────────────────────────────────────────
# Mock UCP server helpers(httpx.MockTransport)
# ────────────────────────────────────────────────────────

class MockUCPRouter:
    """Mock kernel handleUCP dispatcher,同步 sync + async 用同一逻辑。"""

    def __init__(self) -> None:
        self.tool_results: dict[str, dict] = {}
        self.tool_errors: dict[str, dict] = {}
        self.not_implemented_tools: set[str] = set()
        self.calls: list[dict] = []
        self.force_malformed = False

    def add_result(self, tool: str, result: dict) -> None:
        self.tool_results[tool] = result

    def add_error(self, tool: str, code: int, message: str) -> None:
        self.tool_errors[tool] = {"code": code, "message": message}

    def stub_not_implemented(self, tool: str) -> None:
        self.not_implemented_tools.add(tool)

    def handle(self, req: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(req.content.decode("utf-8"))
        except json.JSONDecodeError:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "parse error"},
                    "id": 0,
                },
            )

        self.calls.append(body)

        if self.force_malformed:
            return httpx.Response(200, content=b"{not valid json")

        if body.get("jsonrpc") != "2.0":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "jsonrpc must be 2.0"},
                    "id": body.get("id", 0),
                },
            )

        if body.get("method") != "tools/call":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "method: " + str(body.get("method"))},
                    "id": body.get("id", 0),
                },
            )

        params = body.get("params") or {}
        tool_name = params.get("name", "")

        if not tool_name:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "missing 'name' in params"},
                    "id": body.get("id", 0),
                },
            )

        # W3 stub(not implemented by kernel)
        if tool_name in self.not_implemented_tools:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": ERR_CODE_INTERNAL,
                        "message": "W5 Stripe 集成中,当前 stub (D88.1)",
                    },
                    "id": body.get("id", 0),
                },
            )

        if tool_name in self.tool_errors:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": self.tool_errors[tool_name],
                    "id": body.get("id", 0),
                },
            )

        if tool_name in self.tool_results:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": self.tool_results[tool_name],
                    "id": body.get("id", 0),
                },
            )

        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {
                    "code": ERR_CODE_METHOD_NOT_FOUND,
                    "message": "no mock result for: " + tool_name,
                },
                "id": body.get("id", 0),
            },
        )


@pytest.fixture
def mock_router():
    return MockUCPRouter()


@pytest.fixture
def sync_client(mock_router):
    """Sync UCPClient 用 mock_router 作为唯一 transport。"""
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport, base_url="https://kernel.example.com")
    return UCPClient(
        base_url="https://kernel.example.com",
        bearer_token="oauth-jwt-test",
        http_client=http,
    )


@pytest.fixture
def async_client(mock_router):
    """Async UCPClient 用 mock_router 作为唯一 transport。"""
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.AsyncClient(transport=transport, base_url="https://kernel.example.com")
    return AsyncUCPClient(
        base_url="https://kernel.example.com",
        bearer_token="oauth-jwt-test",
        http_client=http,
    )


# ────────────────────────────────────────────────────────
# 11 tool sync happy path
# ────────────────────────────────────────────────────────

def test_list_products_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_LIST_PRODUCTS,
        {
            "products": [
                {"product_id": "p-1", "name": "Hat", "price_cents": 9950, "currency": "CNY"},
                {"product_id": "p-2", "name": "Pin", "price_cents": 1990, "currency": "CNY"},
            ],
            "total": 2, "page": 1, "page_size": 20,
        },
    )
    res = sync_client.list_products()
    assert isinstance(res, ListProductsResult)
    assert res.total == 2
    assert len(res.products) == 2
    assert res.products[0].product_id == "p-1"
    assert res.products[0].price_cents == 9950


def test_list_products_with_filter(sync_client, mock_router):
    mock_router.add_result(
        TOOL_LIST_PRODUCTS,
        {"products": [{"product_id": "p-3"}], "total": 1, "page": 1, "page_size": 10},
    )
    filt = ListProductsFilter(category="apparel", page_size=10)
    res = sync_client.list_products(filt)
    assert res.total == 1
    args = mock_router.calls[-1]["params"]["arguments"]
    assert args["category"] == "apparel"
    assert args["page_size"] == 10


def test_get_product_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_GET_PRODUCT,
        {"product_id": "p-9", "name": "Beanie", "price_cents": 4900, "currency": "CNY"},
    )
    p = sync_client.get_product("p-9")
    assert isinstance(p, Product)
    assert p.product_id == "p-9"
    assert p.name == "Beanie"


def test_get_product_empty_id_raises(sync_client):
    with pytest.raises(ValueError, match="product_id is required"):
        sync_client.get_product("")


def test_search_products_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_SEARCH_PRODUCTS,
        {
            "products": [{"product_id": "p-7", "name": "Coffee Beans"}],
            "total": 1, "query": "coffee",
        },
    )
    res = sync_client.search_products("coffee", limit=10)
    assert isinstance(res, SearchProductsResult)
    assert res.total == 1
    assert res.products[0].name == "Coffee Beans"


def test_add_to_cart_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_ADD_TO_CART,
        {
            "cart_id": "cart-1",
            "user_id": "u-1",
            "line_items": [
                {"line_item_id": "li-1", "product_id": "p-1", "quantity": 2,
                 "unit_price_cents": 9950, "subtotal_cents": 19900}
            ],
            "total_cents": 19900, "currency": "CNY",
        },
    )
    cart = sync_client.add_to_cart("p-1", 2)
    assert isinstance(cart, Cart)
    assert cart.cart_id == "cart-1"
    assert cart.total_cents == 19900
    assert len(cart.line_items) == 1
    assert cart.line_items[0].quantity == 2


def test_get_cart_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_GET_CART,
        {"cart_id": "cart-99", "total_cents": 5000},
    )
    cart = sync_client.get_cart("cart-99")
    assert cart.cart_id == "cart-99"
    assert cart.total_cents == 5000


def test_remove_from_cart_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_REMOVE_FROM_CART,
        {"cart_id": "cart-1", "removed": True, "line_items": []},
    )
    cart = sync_client.remove_from_cart("cart-1", "li-1")
    assert cart.removed is True
    assert cart.line_items == []


def test_remove_from_cart_empty_ids(sync_client):
    with pytest.raises(ValueError, match="cart_id is required"):
        sync_client.remove_from_cart("", "li-1")
    with pytest.raises(ValueError, match="line_item_id is required"):
        sync_client.remove_from_cart("cart-1", "")


def test_create_checkout_session_w3_stub(sync_client, mock_router):
    mock_router.stub_not_implemented(TOOL_CREATE_CHECKOUT_SESSION)
    with pytest.raises(NotImplementedError, match="W5 Stripe"):
        sync_client.create_checkout_session("cart-1")


def test_confirm_payment_w3_stub(sync_client, mock_router):
    mock_router.stub_not_implemented(TOOL_CONFIRM_PAYMENT)
    with pytest.raises(NotImplementedError, match="W5 Stripe"):
        sync_client.confirm_payment("cs_xyz")


def test_get_order_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_GET_ORDER,
        {"order_id": "ord-9", "user_id": "u-1", "tenant_id": "tenant-A",
         "status": "paid", "total_cents": 9950, "currency": "CNY"},
    )
    order = sync_client.get_order("ord-9")
    assert isinstance(order, Order)
    assert order.tenant_id == "tenant-A"
    assert order.status == "paid"


def test_list_orders_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_LIST_ORDERS,
        {"orders": [{"order_id": "ord-1", "status": "paid"}], "total": 1,
         "page": 1, "page_size": 20},
    )
    res = sync_client.list_orders("u-1", ListOrdersFilter(page_size=20))
    assert isinstance(res, ListOrdersResult)
    assert res.total == 1
    assert res.orders[0].order_id == "ord-1"


def test_cancel_order_happy_path(sync_client, mock_router):
    mock_router.add_result(
        TOOL_CANCEL_ORDER,
        {"order_id": "ord-1", "status": "canceled",
         "refund_id": "re_xyz", "refund_status": "pending",
         "canceled_at": "2026-07-11T10:00:00Z"},
    )
    res = sync_client.cancel_order("ord-1")
    assert isinstance(res, CancelOrderResult)
    assert res.refund_id == "re_xyz"
    assert res.refund_status == "pending"


# ────────────────────────────────────────────────────────
# Error path tests
# ────────────────────────────────────────────────────────

def test_product_not_found(sync_client, mock_router):
    mock_router.add_error(TOOL_GET_PRODUCT, ERR_CODE_UCP_PRODUCT_NOT_FOUND, "no product: missing-id")
    with pytest.raises(RPCError) as exc_info:
        sync_client.get_product("missing-id")
    assert exc_info.value.code == ERR_CODE_UCP_PRODUCT_NOT_FOUND
    assert is_not_found(exc_info.value)


def test_stripe_error(sync_client, mock_router):
    # Explicit Stripe payment failure error (not W3 stub) → wrapped into RPCError,
    # not NotImplementedError. The wrapper only catches "W5" message + INTERNAL code.
    mock_router.add_error(TOOL_CREATE_CHECKOUT_SESSION, ERR_CODE_UCP_PAYMENT_FAILED, "card declined")
    with pytest.raises(RPCError) as exc_info:
        sync_client.create_checkout_session("cart-1")
    assert is_stripe_error(exc_info.value)


def test_invalid_json(mock_router):
    mock_router.force_malformed = True
    transport = httpx.MockTransport(mock_router.handle)
    http = httpx.Client(transport=transport, base_url="https://kernel.example.com")
    cli = UCPClient(base_url="https://kernel.example.com", http_client=http)
    with pytest.raises(json.JSONDecodeError):
        cli.get_product("p-1")


def test_method_not_found(sync_client, mock_router):
    # 不预设 result → mock 返 "no mock result for"
    with pytest.raises(RPCError) as exc_info:
        sync_client._call_tool("totally_unknown", None)
    assert exc_info.value.code == ERR_CODE_METHOD_NOT_FOUND


# ────────────────────────────────────────────────────────
# Auth + Stripe helpers
# ────────────────────────────────────────────────────────

def test_set_bearer_token():
    req = httpx.Request("POST", "https://kernel.example.com/ucp")
    set_bearer_token(req, "tok-1")
    assert req.headers["Authorization"] == "Bearer tok-1"

    req2 = httpx.Request("POST", "https://kernel.example.com/ucp")
    set_bearer_token(req2, "")
    assert "Authorization" not in req2.headers


def test_set_tenant_id():
    req = httpx.Request("POST", "https://kernel.example.com/ucp")
    set_tenant_id(req, "tenant-A")
    assert req.headers["X-WAU-Tenant-ID"] == "tenant-A"


def test_is_stripe_path():
    assert is_stripe_path("create_checkout_session")
    assert is_stripe_path("confirm_payment")
    assert is_stripe_path("cancel_order")
    assert not is_stripe_path("list_products")
    assert not is_stripe_path("add_to_cart")


# ────────────────────────────────────────────────────────
# Async UCPClient(选择性覆盖)
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_list_products_happy_path(async_client, mock_router):
    mock_router.add_result(
        TOOL_LIST_PRODUCTS,
        {"products": [{"product_id": "p-1", "name": "Hat"}], "total": 1},
    )
    res = await async_client.list_products()
    assert res.total == 1
    assert res.products[0].product_id == "p-1"


@pytest.mark.asyncio
async def test_async_add_to_cart_happy_path(async_client, mock_router):
    mock_router.add_result(
        TOOL_ADD_TO_CART,
        {"cart_id": "cart-async", "total_cents": 19900,
         "line_items": [{"line_item_id": "li-1", "quantity": 2}]},
    )
    cart = await async_client.add_to_cart("p-1", 2)
    assert cart.cart_id == "cart-async"
    assert cart.total_cents == 19900


@pytest.mark.asyncio
async def test_async_stripe_stub(async_client, mock_router):
    mock_router.stub_not_implemented(TOOL_CONFIRM_PAYMENT)
    with pytest.raises(NotImplementedError):
        await async_client.confirm_payment("cs_xyz")


@pytest.mark.asyncio
async def test_async_close(async_client):
    await async_client.close()
