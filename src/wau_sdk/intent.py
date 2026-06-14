"""IntentService — M3.1 gRPC stub

v0.6.0 M3 W6: P2 stub,所有方法返 NotImplementedError。
v0.6.0 M3.1: 实装 wau.intent.v1.IntentService 4 RPC (ParseIntent/RecommendAgent/ListAgents/HealthCheck)。
"""

from __future__ import annotations

from typing import Any

from wau_sdk._errors import NotImplementedError as WauNotImplementedError


class IntentService:
    """同步 IntentService (gRPC stub)"""

    def recommend(self, prompt: str, top_k: int = 1) -> Any:
        raise WauNotImplementedError("IntentService.recommend: P2 gRPC stub, M3.1 实装")

    def parse_intent(self, text: str) -> Any:
        raise WauNotImplementedError("IntentService.parse_intent: P2 gRPC stub, M3.1 实装")

    def list_agents(self, online_only: bool = True) -> Any:
        raise WauNotImplementedError("IntentService.list_agents: P2 gRPC stub, M3.1 实装")

    def health_check(self) -> Any:
        raise WauNotImplementedError("IntentService.health_check: P2 gRPC stub, M3.1 实装")


class AsyncIntentService:
    """异步 IntentService (gRPC stub)"""

    async def recommend(self, prompt: str, top_k: int = 1) -> Any:
        raise WauNotImplementedError("AsyncIntentService.recommend: P2 gRPC stub, M3.1 实装")

    async def parse_intent(self, text: str) -> Any:
        raise WauNotImplementedError("AsyncIntentService.parse_intent: P2 gRPC stub, M3.1 实装")

    async def list_agents(self, online_only: bool = True) -> Any:
        raise WauNotImplementedError("AsyncIntentService.list_agents: P2 gRPC stub, M3.1 实装")

    async def health_check(self) -> Any:
        raise WauNotImplementedError("AsyncIntentService.health_check: P2 gRPC stub, M3.1 实装")
