"""AgentsService 单测 — 7 方法(respx mock kernel)"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import Agent, ClientOptions, RetryConfig, CircuitConfig


@pytest.fixture
def client(mock_kernel: respx.MockRouter) -> wau_sdk.Client:
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        yield c


@pytest.fixture
def mock_kernel() -> respx.MockRouter:
    with respx.mock(base_url="http://mock-kernel:18400") as router:
        yield router


def test_agents_list_default(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/registry/agents", params={"page": "1", "pageSize": "10"}).mock(
        return_value=httpx.Response(200, json={
            "agents": [
                {"name": "Whis", "url": "http://whis:18800", "skills": ["general"], "status": "online", "trust": 0.85},
                {"name": "Jarvis", "url": "http://jarvis:18800", "skills": ["clinical"], "status": "online", "trust": 0.92},
            ],
            "total": 2, "page": 1, "pageSize": 10, "totalPages": 1,
        })
    )
    resp = client.agents.list()
    assert len(resp.agents) == 2
    assert resp.agents[0].name == "Whis"
    assert resp.agents[1].name == "Jarvis"


def test_agents_list_with_filters(mock_kernel: respx.MockRouter) -> None:
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        mock_kernel.get("/registry/agents", params={"page": "2", "pageSize": "5", "skill": "clinical", "status": "online"}).mock(
            return_value=httpx.Response(200, json={
                "agents": [{"name": "Jarvis", "skills": ["clinical"], "status": "online", "trust": 0.9}],
                "total": 1, "page": 2, "pageSize": 5, "totalPages": 1,
            })
        )
        resp = c.agents.list(wau_sdk.PageOptions(page=2, pageSize=5, skill="clinical", status="online"))
    assert len(resp.agents) == 1
    assert resp.agents[0].name == "Jarvis"


def test_agents_iter_yields_all(mock_kernel: respx.MockRouter) -> None:
    """iter 翻页遍历全部 agent"""
    # 2 页,每页 1 个
    mock_kernel.get("/registry/agents", params={"page": "1", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={
            "agents": [{"name": "Whis", "status": "online", "trust": 0.85}],
            "total": 2, "page": 1, "pageSize": 1, "totalPages": 2,
        })
    )
    mock_kernel.get("/registry/agents", params={"page": "2", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={
            "agents": [{"name": "Jarvis", "status": "online", "trust": 0.92}],
            "total": 2, "page": 2, "pageSize": 1, "totalPages": 2,
        })
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        names = [a.name for a in c.agents.iter(wau_sdk.PageOptions(pageSize=1))]
    assert names == ["Whis", "Jarvis"]


def test_agents_get_status(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/registry/agents/jarvis/status").mock(
        return_value=httpx.Response(200, json={
            "name": "jarvis", "status": "online", "trust": 0.9,
            "load": {"activeTasks": 1, "maxCapacity": 10, "cpuUsage": 0.2, "memoryUsage": 0.3},
            "circuit": "closed",
        })
    )
    status = client.agents.get("jarvis")
    assert status.name == "jarvis"
    assert status.status == "online"
    assert status.trust == 0.9
    assert status.circuit == "closed"
    assert status.load.activeTasks == 1


def test_agents_score(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/registry/agents/jarvis/score").mock(
        return_value=httpx.Response(200, json={
            "name": "jarvis", "totalScore": 0.88, "trustScore": 0.9,
            "skillMatch": 0.85, "healthScore": 0.95, "loadScore": 0.8,
        })
    )
    score = client.agents.score("jarvis")
    assert score.name == "jarvis"
    assert score.totalScore == 0.88


def test_agents_register(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/registry/agents/register").mock(
        return_value=httpx.Response(201, json={"name": "new-agent", "registered": True})
    )
    client.agents.register(wau_sdk.AgentRegisterRequest(
        name="new-agent", url="http://new:18800", skills=["demo"], universes=["test"]
    ))


def test_agents_deregister(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.delete("/registry/agents/old").mock(
        return_value=httpx.Response(200, json={"name": "old", "deregistered": True})
    )
    client.agents.deregister("old")


def test_agents_heartbeat(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/registry/agents/heartbeat").mock(
        return_value=httpx.Response(200, json={"received": True})
    )
    client.agents.heartbeat("test-agent")


def test_agents_report_load(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/heartbeat/load").mock(
        return_value=httpx.Response(200, json={"received": True})
    )
    client.agents.report_load("test-agent", wau_sdk.AgentLoad(
        activeTasks=2, maxCapacity=10, cpuUsage=0.5, memoryUsage=0.6
    ))
