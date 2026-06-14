"""5 场景契约测试 — 对齐 wau-go-sdk/tests/contract_test.go

5 场景(clinical/france/pain/sales/rare_disease) 跟 wau-intent 仓 e2e_test/test_submit_l4.py 一致
黄金 JSON 唯一真相源在 ./contract-golden/scenario_*.json (从 wau-go-sdk 复用, ADR-0004)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import ClientOptions, RetryConfig, CircuitConfig
from wau_sdk.types import SubmitRequest

GOLDEN_DIR = Path(__file__).parent / "contract-golden"

# 5 场景 — 跟 wau-go-sdk/tests/contract_test.go + wau-intent e2e 一致
FIVE_SCENARIOS = [
    pytest.param(
        "clinical",
        "I need clinical decision support for a patient",
        "Jarvis",
        ["临床", "决策", "支持", "患者"],
        id="clinical",
    ),
    pytest.param(
        "france",
        "What is the capital of France?",
        "Whis",
        ["paris"],
        id="france",
    ),
    pytest.param(
        "pain",
        "Recommend an over-the-counter pain reliever",
        "Benny",
        ["ibuprofen", "acetaminophen", "pain", "reliever"],
        id="pain",
    ),
    pytest.param(
        "sales",
        "Show me this quarter's sales analytics",
        "Whis",
        ["sales", "analytics", "quarter"],
        id="sales",
    ),
    pytest.param(
        "rare_disease",
        "Help me diagnose a rare disease",
        "Jarvis",
        ["罕见病", "鉴别", "诊断"],
        id="rare_disease",
    ),
]


def _load_golden(scenario: str) -> dict[str, object]:
    """加载黄金 JSON (跟 wau-go-sdk tests/contract-golden/ 一致)"""
    path = GOLDEN_DIR / f"scenario_{scenario}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("scene,prompt,expected_agent,expected_tokens", FIVE_SCENARIOS)
@pytest.mark.contract
def test_5_scenarios_5_of_5_pass(
    scene: str, prompt: str, expected_agent: str, expected_tokens: list[str]
) -> None:
    """5 场景契约 — 走 mock kernel,验证 selected_agent / status / tokens"""
    golden = _load_golden(scene)
    expected_status = str(golden["expected_status"])

    # 构造 mock kernel 响应(基于黄金 JSON)
    mock_response = {
        "task_id": f"task-{scene}-001",
        "status": expected_status,
        "selected_agent": expected_agent,
        "score": 0.85,
        "decision": {
            "selected_agent": expected_agent,
            "score": 0.85,
            "decision_time_ms": 150,
            "candidates": [{"name": expected_agent, "score": 0.85, "reason": f"mock for {scene}"}],
        },
        "a2a_call_ms": 3500,
        # 响应文本(包含 expected_tokens 之一,确保契约 token 匹配)
        "response": f"Mock response with token: {expected_tokens[0]}",
        "source_peer": "wau-python-sdk/0.6.0-preview.1",
        "source_agent_id": "test-runner",
    }

    with respx.mock(base_url="http://mock-kernel:18400") as mock:
        mock.post("/registry/tasks/submit").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        # respx 默认拦截 httpx,需要禁用 SSL 检查 + 确保 base_url 匹配
        with wau_sdk.Client("http://mock-kernel:18400", wau_sdk.ClientOptions(
            retry=wau_sdk.RetryConfig(max_retries=0),
            circuit=wau_sdk.CircuitConfig(enabled=False),
        )) as c:
            resp = c.tasks.submit(SubmitRequest(prompt=prompt, timeout_ms=60000))

    # 验证 1: status
    assert resp.status == expected_status, f"scene={scene}: status={resp.status}, want {expected_status}"

    # 验证 2: selected_agent
    assert resp.selected_agent == expected_agent, (
        f"scene={scene}: selected_agent={resp.selected_agent}, want {expected_agent}"
    )

    # 验证 3: score > 0
    assert resp.score > 0, f"scene={scene}: score={resp.score}, want > 0"

    # 验证 4: response 文本至少包含 1 个期望 token
    response_text = str(resp.response).lower() if resp.response else ""
    matched = any(tok.lower() in response_text for tok in expected_tokens)
    assert matched, (
        f"scene={scene}: response 文本里没找到任何期望 token {expected_tokens}, got: {response_text}"
    )


@pytest.mark.contract
def test_submit_request_prompt_required_raises_api_error() -> None:
    """空 prompt 应被 kernel binding 校验拒绝 → 400 BadRequestError"""
    with respx.mock(base_url="http://mock-kernel:18400") as mock:
        mock.post("/registry/tasks/submit").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": "prompt is required (binding:required)",
                    "code": "bad_request",
                },
            )
        )

        with wau_sdk.Client("http://mock-kernel:18400") as c:
            with pytest.raises(wau_sdk.BadRequestError) as exc_info:
                c.tasks.submit(SubmitRequest(prompt=""))

    assert exc_info.value.status_code == 400


@pytest.mark.contract
def test_404_raises_not_found_error() -> None:
    """GET 不存在的 agent → 404 NotFoundError"""
    with respx.mock(base_url="http://mock-kernel:18400") as mock:
        mock.get("/registry/agents/nonexistent/status").mock(
            return_value=httpx.Response(404, json={"error": "agent not found", "code": "not_found"})
        )

        with wau_sdk.Client("http://mock-kernel:18400") as c:
            with pytest.raises(wau_sdk.NotFoundError) as exc_info:
                c.agents.get("nonexistent")

    assert exc_info.value.status_code == 404
