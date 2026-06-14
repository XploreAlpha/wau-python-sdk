"""错误层级 — 跟 wau-go-sdk errors.go 字段 1:1 对应

所有错误继承 WauError;HTTP 4xx/5xx 自动映射到对应子类(由 Client.do_request 翻译)。
"""

from __future__ import annotations


class WauError(Exception):
    """所有 wau-sdk 错误的基类"""


class APIError(WauError):
    """HTTP 4xx/5xx 错误(从 kernel 响应翻译)

    Attributes:
        status_code: HTTP 状态码
        code: 业务错误码(从响应 body 的 "code" 字段解析)
        message: 业务错误信息
        request_id: 来自响应 header X-Request-ID
        body: 原始响应 body(用于 debug)
    """

    def __init__(
        self,
        status_code: int,
        message: str = "",
        code: str | None = None,
        request_id: str | None = None,
        body: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code or ""
        self.message = message
        self.request_id = request_id or ""
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


class NotFoundError(APIError):
    """404"""

    def __init__(self, message: str = "not found", **kw: object) -> None:
        super().__init__(404, message=message, code="not_found", **kw)


class UnauthorizedError(APIError):
    """401"""

    def __init__(self, message: str = "unauthorized", **kw: object) -> None:
        super().__init__(401, message=message, code="unauthorized", **kw)


class ForbiddenError(APIError):
    """403"""

    def __init__(self, message: str = "forbidden", **kw: object) -> None:
        super().__init__(403, message=message, code="forbidden", **kw)


class BadRequestError(APIError):
    """400"""

    def __init__(self, message: str = "bad request", **kw: object) -> None:
        super().__init__(400, message=message, code="bad_request", **kw)


class ConflictError(APIError):
    """409"""

    def __init__(self, message: str = "conflict", **kw: object) -> None:
        super().__init__(409, message=message, code="conflict", **kw)


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
