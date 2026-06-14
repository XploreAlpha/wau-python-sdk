"""重试装饰器 — 指数退避 + 抖动(对齐 wau-go-sdk retry.go)

策略:max_retries=3 / initial=200ms / max=5s / jitter=0.2
只对**幂等**请求自动重试(5xx + 429 + 网络错)
"""

from __future__ import annotations

import logging
import random
import time
from typing import Awaitable, Callable, TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    Retrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from wau_sdk._errors import APIError, MaxRetriesError, WauError
from wau_sdk._options import RetryConfig

__all__ = ["Retrier", "AsyncRetrier", "is_retryable"]

T = TypeVar("T")
logger = logging.getLogger("wau_sdk.retry")


def is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试(对齐 wau-go-sdk retrier.shouldRetry)

    规则:
    - 5xx APIError: 重试
    - 4xx APIError (非 429): 不重试
    - 429: 重试
    - 网络错 / 超时: 重试
    - 上下文取消: 不重试
    """
    if isinstance(exc, APIError):
        # 5xx + 429 重试
        return exc.status_code >= 500 or exc.status_code == 429
    if isinstance(exc, (httpx.RequestError, ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, WauError):
        # 业务错(NotFound 等)不重试
        return False
    # 未知错误不重试
    return False


class Retrier:
    """同步重试器(对齐 wau-go-sdk retrier + tenacity)"""

    def __init__(self, config: RetryConfig) -> None:
        self._config = config
        # tenacity 参数
        self._stop = stop_after_attempt(config.max_retries + 1)
        # 指数退避 + jitter(tenacity 自带 jitter 支持)
        self._wait = wait_exponential_jitter(
            initial=config.initial_backoff_ms / 1000,
            max=config.max_backoff_ms / 1000,
            jitter=config.jitter,
        )

    def do(self, op: Callable[[], T]) -> T:
        """执行 op,失败按配置重试

        包装 tenacity.Retrying,捕获最后一次异常包装成 MaxRetriesError
        """
        try:
            for attempt in Retrying(
                stop=self._stop,
                wait=self._wait,
                # 用 is_retryable 做谓词:5xx + 429 + 网络错重试,4xx 不重试
                retry=retry_if_exception(lambda exc: is_retryable(exc)),
                reraise=True,
            ):
                with attempt:
                    return op()
        except (APIError, httpx.RequestError, ConnectionError, TimeoutError) as last_exc:
            # MaxRetries=0 时不抛 MaxRetriesError(只调了 1 次,没"耗尽"概念)
            if is_retryable(last_exc) and self._config.max_retries > 0:
                raise MaxRetriesError(last_exc) from last_exc
            raise last_exc


class AsyncRetrier:
    """异步重试器"""

    def __init__(self, config: RetryConfig) -> None:
        self._config = config
        self._stop = stop_after_attempt(config.max_retries + 1)
        self._wait = wait_exponential_jitter(
            initial=config.initial_backoff_ms / 1000,
            max=config.max_backoff_ms / 1000,
            jitter=config.jitter,
        )

    async def do(self, op: Callable[[], Awaitable[T]]) -> T:
        """执行 async op,失败按配置重试"""
        try:
            async for attempt in AsyncRetrying(
                stop=self._stop,
                wait=self._wait,
                retry=retry_if_exception(lambda exc: is_retryable(exc)),
                reraise=True,
            ):
                with attempt:
                    return await op()
        except (APIError, httpx.RequestError, ConnectionError, TimeoutError) as last_exc:
            if is_retryable(last_exc) and self._config.max_retries > 0:
                raise MaxRetriesError(last_exc) from last_exc
            raise last_exc
