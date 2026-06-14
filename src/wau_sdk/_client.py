"""Client 主类 — W6.9 完整实装(目前占位)"""

from __future__ import annotations

import httpx

from wau_sdk._options import ClientOptions, default_options, with_timeout, with_retry_no
from wau_sdk.types import SubmitRequest, SubmitResponse, DecisionInfo


class Client:
    """WAU SDK 同步客户端(占位 — W6.9 完整实装)"""

    def __init__(self, base_url: str, options: ClientOptions | None = None) -> None:
        self._base_url = base_url
        self._options = options or default_options()
        self._http = httpx.Client(
            base_url=base_url,
            timeout=self._options.timeout_ms / 1000,
            headers={"User-Agent": self._options.user_agent},
        )
        # 占位:W6.9 实装这 4 个子服务
        self.tasks = _TasksStub(self)
        self.agents = _AgentsStub(self)
        self.kernel = _KernelStub(self)
        self.intent = _IntentStub(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncClient:
    """WAU SDK 异步客户端(占位 — W6.9 完整实装)"""

    def __init__(self, base_url: str, options: ClientOptions | None = None) -> None:
        self._base_url = base_url
        self._options = options or default_options()
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=self._options.timeout_ms / 1000,
            headers={"User-Agent": self._options.user_agent},
        )

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._http.aclose()

    async def close(self) -> None:
        await self._http.aclose()


# ============================
# W6.9 占位 stub — 4 核心对象
# ============================


class _TasksStub:
    def __init__(self, client: Client) -> None:
        self._client = client

    def submit(self, req: SubmitRequest) -> SubmitResponse:
        raise NotImplementedError("TasksService.submit W6.9 待实装")

    def simulate(self, req: SubmitRequest) -> DecisionInfo:
        raise NotImplementedError("TasksService.simulate W6.9 待实装")


class _AgentsStub:
    def __init__(self, client: Client) -> None:
        self._client = client


class _KernelStub:
    def __init__(self, client: Client) -> None:
        self._client = client


class _IntentStub:
    def __init__(self, client: Client) -> None:
        self._client = client
