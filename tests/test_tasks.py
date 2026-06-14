"""TasksService 单测 — 3 方法(respx mock kernel)"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import ClientOptions, RetryConfig, CircuitConfig


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


def test_tasks_submit_success(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(200, json={
            "task_id": "task-001",
            "status": "completed",
            "selected_agent": "Whis",
            "score": 0.85,
            "decision": {
                "selected_agent": "Whis", "score": 0.85, "decision_time_ms": 100,
                "candidates": [{"name": "Whis", "score": 0.85, "reason": "mock"}],
            },
            "a2a_call_ms": 2000,
            "response": "Echo: hello",
            "source_peer": "wau-python-sdk/0.6.0-preview.1",
        })
    )
    resp = client.tasks.submit(wau_sdk.SubmitRequest(prompt="hello", timeout_ms=30000))
    assert resp.status == "completed"
    assert resp.selected_agent == "Whis"
    assert resp.score == 0.85
    assert resp.decision.decision_time_ms == 100
    assert len(resp.decision.candidates) == 1
    assert resp.decision.candidates[0].name == "Whis"


def test_tasks_submit_with_timeout(mock_kernel: respx.MockRouter) -> None:
    """timeout_ms 应序列化到 body"""
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(200, json={
            "task_id": "t1", "status": "completed", "selected_agent": "Whis", "score": 0.5,
            "decision": {"selected_agent": "Whis", "score": 0.5, "decision_time_ms": 50},
        })
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        c.tasks.submit(wau_sdk.SubmitRequest(prompt="x", timeout_ms=15000))


def test_tasks_submit_no_timeout(mock_kernel: respx.MockRouter) -> None:
    """不传 timeout_ms 时 body 不应含该字段"""
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(200, json={
            "task_id": "t1", "status": "completed", "selected_agent": "Whis", "score": 0.5,
            "decision": {"selected_agent": "Whis", "score": 0.5, "decision_time_ms": 50},
        })
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        c.tasks.submit(wau_sdk.SubmitRequest(prompt="x"))


def test_tasks_submit_empty_prompt_raises_400(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(400, json={"error": "prompt is required", "code": "bad_request"})
    )
    with pytest.raises(wau_sdk.BadRequestError):
        client.tasks.submit(wau_sdk.SubmitRequest(prompt=""))


def test_tasks_simulate(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    """simulate 应返 DecisionInfo,不含 a2a_call_ms / response"""
    mock_kernel.post("/registry/tasks/simulate").mock(
        return_value=httpx.Response(200, json={
            "selected_agent": "Whis", "score": 0.55, "decision_time_ms": 100,
            "candidates": [{"name": "Whis", "score": 0.55, "reason": "general"}],
        })
    )
    decision = client.tasks.simulate(wau_sdk.SubmitRequest(prompt="test"))
    assert decision.selected_agent == "Whis"
    assert decision.score == 0.55


def test_tasks_get(mock_kernel: respx.MockRouter, client: wau_sdk.Client) -> None:
    mock_kernel.get("/registry/tasks/task-001").mock(
        return_value=httpx.Response(200, json={
            "taskId": "task-001", "message": "echo", "sourcePeer": "test",
            "status": "completed", "assignedAgent": "Whis",
            "createdAt": 1718342400, "updatedAt": 1718342401,
        })
    )
    task = client.tasks.get("task-001")
    assert task.taskId == "task-001"
    assert task.status == "completed"
    assert task.assignedAgent == "Whis"


def test_tasks_submit_5xx_raises_api_error(mock_kernel: respx.MockRouter) -> None:
    """5xx 抛 APIError(基类,不进 CircuitOpen)"""
    mock_kernel.post("/registry/tasks/submit").mock(
        return_value=httpx.Response(500, json={"error": "internal error"})
    )
    with wau_sdk.Client("http://mock-kernel:18400", ClientOptions(
        retry=RetryConfig(max_retries=0),
        circuit=CircuitConfig(enabled=False),
    )) as c:
        with pytest.raises(wau_sdk.APIError) as exc_info:
            c.tasks.submit(wau_sdk.SubmitRequest(prompt="hello"))
    assert exc_info.value.status_code == 500
