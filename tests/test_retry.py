"""Retry 单测 — is_retryable + tenacity 触发"""

from __future__ import annotations

import httpx
import pytest

from wau_sdk._errors import (
    APIError,
    BadRequestError,
    CircuitOpenError,
    MaxRetriesError,
    NotFoundError,
    UnauthorizedError,
)
from wau_sdk._options import RetryConfig
from wau_sdk._retry import Retrier, is_retryable


def test_is_retryable_5xx_returns_true() -> None:
    for code in (500, 502, 503, 504):
        assert is_retryable(APIError(code, "server error")) is True


def test_is_retryable_429_returns_true() -> None:
    assert is_retryable(APIError(429, "rate limit")) is True


def test_is_retryable_4xx_returns_false() -> None:
    for code in (400, 401, 403, 404, 409):
        assert is_retryable(APIError(code, "client error")) is False


def test_is_retryable_network_error_returns_true() -> None:
    assert is_retryable(ConnectionError("dial tcp: connection refused")) is True
    assert is_retryable(TimeoutError("read timeout")) is True


def test_is_retryable_circuit_open_returns_false() -> None:
    """CircuitOpenError 不应重试(避免雪崩)"""
    assert is_retryable(CircuitOpenError()) is False


def test_is_retryable_none_returns_false() -> None:
    assert is_retryable(None) is False  # type: ignore[arg-type]


def test_retrier_max_retries_zero_calls_once() -> None:
    """MaxRetries=0 应只调 1 次(无重试),直接抛原 APIError"""
    r = Retrier(RetryConfig(max_retries=0))
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        raise APIError(500, "server error")

    with pytest.raises(APIError) as exc_info:
        r.do(op)
    assert calls == 1
    assert exc_info.value.status_code == 500


def test_retrier_4xx_does_not_retry() -> None:
    """4xx 不重试(业务错)"""
    r = Retrier(RetryConfig(max_retries=3))
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        raise NotFoundError("not found")

    with pytest.raises(NotFoundError):
        r.do(op)
    assert calls == 1  # 不重试


def test_retrier_5xx_retries_until_max() -> None:
    """5xx 触发重试,达到 max_retries 后返 MaxRetriesError"""
    r = Retrier(RetryConfig(max_retries=2))  # 1 + 2 retries = 3 calls
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        raise APIError(503, "service unavailable")

    with pytest.raises(MaxRetriesError) as exc_info:
        r.do(op)
    assert calls == 3  # 1 + 2 retries
    assert exc_info.value.last_error.status_code == 503


def test_retrier_5xx_recovers_on_retry() -> None:
    """5xx 重试,中间一次成功,返成功结果"""
    r = Retrier(RetryConfig(max_retries=3))
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise APIError(502, "bad gateway")
        return "success"

    result = r.do(op)
    assert result == "success"
    assert calls == 3  # 2 失败 + 1 成功


def test_retrier_first_success_no_retry() -> None:
    """首次成功不重试"""
    r = Retrier(RetryConfig(max_retries=3))
    calls = 0

    def op() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = r.do(op)
    assert result == "ok"
    assert calls == 1
