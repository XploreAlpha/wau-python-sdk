"""错误层级 — 跟 wau-go-sdk errors.go 字段 1:1 对齐

所有错误继承 WauError;HTTP 4xx/5xx 自动映射到对应子类(由 Transport._raise_for_status 翻译)。

API 设计:
- APIError 接受 (status_code, message, code, request_id, body) — 位置 1 是 status_code
- 子类用 `default_status_code` / `default_code` 类属性
- 子类重写 `__init__` 支持简化形式: NotFoundError("custom msg") 走 default 404
- Transport 用完整形式: err_cls(status_code, message=..., code=..., request_id=..., body=...)
"""

from __future__ import annotations


class WauError(Exception):
    """所有 wau-sdk 错误的基类"""


class APIError(WauError):
    """HTTP 4xx/5xx 错误基类"""

    default_status_code: int = 0
    default_code: str = ""

    def __init__(
        self,
        status_code: int,
        message: str = "",
        code: str = "",
        request_id: str = "",
        body: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        self.body = body or b""
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"status={self.status_code}"]
        if self.code:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        if self.message:
            parts.append(f"message={self.message}")
        if self.body:
            try:
                body_str = self.body.decode("utf-8", errors="replace")[:200]
                parts.append(f"body={body_str!r}")
            except Exception:
                pass
        return f"WauAPIError({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, APIError):
            return NotImplemented
        return self.status_code == other.status_code

    def __hash__(self) -> int:
        return hash(self.status_code)


# 4xx/5xx 子类工厂 — 闭包捕获 status_code/code 默认值
def _make_api_error_subclass(
    name: str, default_status_code: int, default_code: str
) -> type[APIError]:
    """生成 APIError 子类,支持:
    - NotFoundError("custom msg") — 简化形式(用 default 状态码)
    - err_cls(404, message="...", code="...", request_id="...", body=b"...") — Transport 完整形式
    """

    def __init__(
        self,
        *args: object,
        status_code: int | None = None,
        message: str = "",
        code: str = "",
        request_id: str = "",
        body: bytes | None = None,
    ) -> None:
        # 简化形式:NotFoundError("custom msg") — 1 个位置 str 参数
        if len(args) == 1 and isinstance(args[0], str):
            message = str(args[0])
        # 完整形式 1:err_cls(404, message=...) — 1 个位置 int(实际 status_code)
        if len(args) == 1 and isinstance(args[0], int):
            status_code = int(args[0])
        # 完整形式 2:err_cls(status_code=404, message=...) — 关键字
        final_status = status_code if status_code is not None else default_status_code
        # super() 走 APIError.__init__,接受 status_code 位置参数
        APIError.__init__(
            self,
            status_code=final_status,
            message=message,
            code=code or default_code,
            request_id=request_id,
            body=body,
        )

    cls_dict: dict[str, object] = {
        "default_status_code": default_status_code,
        "default_code": default_code,
        "__init__": __init__,
        "__doc__": f"HTTP {default_status_code} 错误",
    }
    return type(name, (APIError,), cls_dict)


# 4xx/5xx 错误子类
NotFoundError = _make_api_error_subclass("NotFoundError", 404, "not_found")
UnauthorizedError = _make_api_error_subclass("UnauthorizedError", 401, "unauthorized")
ForbiddenError = _make_api_error_subclass("ForbiddenError", 403, "forbidden")
BadRequestError = _make_api_error_subclass("BadRequestError", 400, "bad_request")
ConflictError = _make_api_error_subclass("ConflictError", 409, "conflict")


class CircuitOpenError(WauError):
    """熔断开 — kernel 服务暂不可用,30s 后 HalfOpen 恢复"""

    def __init__(self, message: str = "circuit breaker is open") -> None:
        super().__init__(message)


class MaxRetriesError(WauError):
    """重试耗尽 — 包 last_error 作为 __cause__"""

    def __init__(self, last_error: Exception, message: str = "max retries exceeded") -> None:
        self.last_error = last_error
        super().__init__(f"{message}: {last_error}")


# W6 stub: gRPC IntentService 还没实装
class NotImplementedError(WauError):
    """P2 stub(避免跟 builtin NotImplementedError 重名)"""
