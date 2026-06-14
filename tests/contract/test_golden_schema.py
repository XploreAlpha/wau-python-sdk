"""黄金 JSON schema 验证 — 5 场景黄金文件必含字段"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "contract-golden"


@pytest.mark.contract
def test_golden_files_count() -> None:
    """5 个黄金 JSON 必须全在"""
    files = list(GOLDEN_DIR.glob("scenario_*.json"))
    assert len(files) == 5, f"黄金 JSON 数 = {len(files)}, want 5"


@pytest.mark.parametrize(
    "scenario",
    ["clinical", "france", "pain", "sales", "rare_disease"],
)
@pytest.mark.contract
def test_golden_schema(scenario: str) -> None:
    """每个黄金 JSON 必含字段:scenario/prompt/expected_selected_agent/expected_status/kernel_response"""
    path = GOLDEN_DIR / f"scenario_{scenario}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in ("scenario", "prompt", "expected_selected_agent", "expected_status", "kernel_response"):
        assert key in data, f"scenario_{scenario}.json 缺字段 {key!r}"
    assert data["scenario"] == scenario
    assert isinstance(data["prompt"], str) and len(data["prompt"]) > 0
    assert isinstance(data["expected_selected_agent"], str) and len(data["expected_selected_agent"]) > 0
    assert isinstance(data["expected_status"], str) and len(data["expected_status"]) > 0
    assert isinstance(data["kernel_response"], dict)
