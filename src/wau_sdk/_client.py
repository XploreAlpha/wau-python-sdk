"""Client 主类 — 串起所有装饰器(retry + circuit + auth + transport)

调用链:
    Service method → Client.do_request → Retrier.do → Circuit.Guard → Transport.do → HTTP

对齐 wau-go-sdk Client.doWithRetry 设计。
"""

from __future__ import annotations

import logging

from wau_sdk._auth import Signer
from wau_sdk._circuit import Breaker
from wau_sdk._options import ClientOptions, default_options
from wau_sdk._retry import AsyncRetrier, Retrier
from wau_sdk._transport import AsyncTransport, Transport
from wau_sdk.agents import AgentsService, AsyncAgentsService
from wau_sdk.intent import AsyncIntentService, IntentService
from wau_sdk.kernel import AsyncKernelService, KernelService
from wau_sdk.tasks import AsyncTasksService, TasksService

__all__ = ["Client", "AsyncClient"]


class Client:
    """WAU SDK 同步客户端

    用法::

        with wau_sdk.Client("http://localhost:18400") as c:
            resp = c.tasks.submit(SubmitRequest(prompt="hello"))
    """

    def __init__(self, base_url: str, options: ClientOptions | None = None) -> None:
        self._base_url = base_url
        self._options = options or default_options()

        # 装饰器层(顺序:auth → transport → circuit → retry)
        # auth
        self._signer: Signer | None = None
        if self._options.auth is not None:
            self._signer = Signer(self._options.auth)

        # circuit(熔断)
        self._circuit: Breaker | None = None
        if self._options.circuit.enabled:
            self._circuit = Breaker(
                failure_threshold=self._options.circuit.failure_threshold,
                recovery_timeout_s=self._options.circuit.open_timeout_ms / 1000,
            )

        # transport(httpx)
        self._transport = Transport(
            base_url=base_url,
            options=self._options,
            signer=self._signer,
            circuit=self._circuit,
        )

        # retry
        self._retrier = Retrier(self._options.retry)

        # 4 子服务
        self.kernel = KernelService(self)
        self.agents = AgentsService(self)
        self.tasks = TasksService(self)
        self.intent = IntentService()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def options(self) -> ClientOptions:
        return self._options

    def circuit_state(self) -> str:
        """返回 SDK 内部熔断状态(debug / metrics 用)

        "closed" / "open" / "half-open"
        """
        if self._circuit is None:
            return "closed"
        state = self._circuit.get_state("wau-kernel")
        return {0: "closed", 1: "open", 2: "half-open"}[int(state)]

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncClient:
    """WAU SDK 异步客户端(API 镜像 Client)

    用法::

        async with wau_sdk.AsyncClient("http://localhost:18400") as c:
            resp = await c.tasks.submit(SubmitRequest(prompt="hello"))
    """

    def __init__(self, base_url: str, options: ClientOptions | None = None) -> None:
        self._base_url = base_url
        self._options = options or default_options()

        self._signer: Signer | None = None
        if self._options.auth is not None:
            self._signer = Signer(self._options.auth)

        self._circuit: Breaker | None = None
        if self._options.circuit.enabled:
            self._circuit = Breaker(
                failure_threshold=self._options.circuit.failure_threshold,
                recovery_timeout_s=self._options.circuit.open_timeout_ms / 1000,
            )

        self._transport = AsyncTransport(
            base_url=base_url,
            options=self._options,
            signer=self._signer,
            circuit=self._circuit,
        )

        self._retrier = AsyncRetrier(self._options.retry)

        self.kernel = AsyncKernelService(self)
        self.agents = AsyncAgentsService(self)
        self.tasks = AsyncTasksService(self)
        self.intent = AsyncIntentService()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def options(self) -> ClientOptions:
        return self._options

    def circuit_state(self) -> str:
        if self._circuit is None:
            return "closed"
        state = self._circuit.get_state("wau-kernel")
        return {0: "closed", 1: "open", 2: "half-open"}[int(state)]

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
