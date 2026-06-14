"""HTTP transport 层 — httpx + 装饰器链

调用链:
    Caller → Client.do_request → Retrier.do → Circuit.Guard → Transport.do → HTTP

设计原则:
- Transport 不知道 retry / circuit(由上层装饰)
- Transport 只做 JSON marshal + 4xx/5xx → APIError 翻译
- 鉴权由 Client 注入(每次请求前 sign + 设 header)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from wau_sdk._auth import Signer
from wau_sdk._circuit import Breaker
from wau_sdk._errors import (
    APIError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from wau_sdk._options import ClientOptions

__all__ = ["Transport"]

logger = logging.getLogger("wau_sdk.transport")

# 状态码 → APIError 子类映射
_STATUS_MAP: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
}


class Transport:
    """同步 HTTP transport(httpx 包装)"""

    def __init__(
        self,
        base_url: str,
        options: ClientOptions,
        signer: Signer | None = None,
        circuit: Breaker | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._options = options
        self._signer = signer
        self._circuit = circuit
        # httpx.Client(允许外部注入 transport 便于测试)
        self._http = options.transport or httpx.Client(
            base_url=self._base_url,
            timeout=options.timeout_ms / 1000,
            headers={"User-Agent": options.user_agent},
        )

    @property
    def http(self) -> httpx.Client:
        """暴露底层 httpx 客户端(高级用法 / 测试)"""
        return self._http

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """构建请求 headers(包含 Bearer token 如果有 signer)"""
        headers: dict[str, str] = {
            "User-Agent": self._options.user_agent,
            "Accept": "application/json",
        }
        if self._signer is not None:
            headers["Authorization"] = f"Bearer {self._signer.sign()}"
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """执行一次 HTTP 请求,返回解析后的 JSON

        Args:
            method: GET/POST/PUT/DELETE
            path: 端点路径(以 / 开头,会拼到 base_url)
            body: 请求 body(可 JSON marshal)
            params: query string 参数

        Returns:
            解析后的 JSON(任意类型,可能 None)

        Raises:
            APIError: HTTP 4xx/5xx
            httpx.RequestError: 网络错
        """
        headers = self._build_headers()
        json_body: str | None = None
        if body is not None:
            json_body = json.dumps(body, default=str)
            headers["Content-Type"] = "application/json"

        url = path if path.startswith("/") else f"/{path}"

        resp = self._http.request(
            method=method,
            url=url,
            params=params,
            content=json_body,
            headers=headers,
        )

        # 4xx/5xx → APIError 子类
        if resp.status_code >= 400:
            self._raise_for_status(resp)

        # 2xx → 返回 JSON(可能为空)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise APIError(
                status_code=resp.status_code,
                message=f"invalid JSON response: {e}",
                body=resp.content,
                request_id=resp.headers.get("X-Request-ID", ""),
            ) from e

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """根据状态码抛对应 APIError"""
        err_cls = _STATUS_MAP.get(resp.status_code, APIError)
        request_id = resp.headers.get("X-Request-ID", "")
        try:
            body_dict = resp.json()
            message = body_dict.get("error") or body_dict.get("message") or ""
            code = body_dict.get("code", "")
        except Exception:
            message = resp.text[:200]
            code = ""
        # 全部用关键字参数(子类形参顺序不同,关键字最安全)
        raise err_cls(
            status_code=resp.status_code,
            message=message,
            code=code,
            request_id=request_id,
            body=resp.content,
        )

    def close(self) -> None:
        self._http.close()


class AsyncTransport:
    """异步 HTTP transport(httpx.AsyncClient 包装)"""

    def __init__(
        self,
        base_url: str,
        options: ClientOptions,
        signer: Signer | None = None,
        circuit: Breaker | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._options = options
        self._signer = signer
        self._circuit = circuit
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=options.timeout_ms / 1000,
            headers={"User-Agent": options.user_agent},
        )

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": self._options.user_agent,
            "Accept": "application/json",
        }
        if self._signer is not None:
            headers["Authorization"] = f"Bearer {self._signer.sign()}"
        if extra:
            headers.update(extra)
        return headers

    async def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = self._build_headers()
        json_body: str | None = None
        if body is not None:
            json_body = json.dumps(body, default=str)
            headers["Content-Type"] = "application/json"

        url = path if path.startswith("/") else f"/{path}"

        resp = await self._http.request(
            method=method,
            url=url,
            params=params,
            content=json_body,
            headers=headers,
        )

        if resp.status_code >= 400:
            self._raise_for_status(resp)

        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise APIError(
                status_code=resp.status_code,
                message=f"invalid JSON response: {e}",
                body=resp.content,
                request_id=resp.headers.get("X-Request-ID", ""),
            ) from e

    def _raise_for_status(self, resp: httpx.Response) -> None:
        err_cls = _STATUS_MAP.get(resp.status_code, APIError)
        request_id = resp.headers.get("X-Request-ID", "")
        try:
            body_dict = resp.json()
            message = body_dict.get("error") or body_dict.get("message") or ""
            code = body_dict.get("code", "")
        except Exception:
            message = resp.text[:200]
            code = ""
        raise err_cls(
            status_code=resp.status_code,
            message=message,
            code=code,
            request_id=request_id,
            body=resp.content,
        )

    async def close(self) -> None:
        await self._http.aclose()
