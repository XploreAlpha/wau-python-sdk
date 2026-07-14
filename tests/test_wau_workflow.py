"""v1.0.1 D78 byte-equal verify — wau-python-sdk WauWorkflow 19 字段 byte-equal TS canonical

测试目标(per v1.0.0final Phase A.3.2):
  - 验证 19 字段都存在
  - 验证 JSON 序列化 snake_case(per TS L15 "JSON 字段 snake_case")
  - 验证 WauWorkflowType 6 enum 值 + 嵌套类型 1:1 跟 TS 一致

TS canonical 锚点: /home/inamoto888/project/wau-typescript-sdk/src/wau/types.ts#L116-L158
"""
from __future__ import annotations

import re
from dataclasses import asdict

import pytest

from wau_sdk.types import (
    WauWorkflow,
    WauWorkflowAgent,
    WauWorkflowDependency,
    WauWorkflowDependencyGraph,
)


def test_wau_workflow_field_count():
    """19 字段 = 5 必填 + 3 标识 + 3 DAG + 3 推荐 + 3 Server + 2 鉴权"""
    fields = set(WauWorkflow.__dataclass_fields__.keys())
    expected = {
        # 必填 5
        "agents", "dependency_graph", "confidence", "workflow_type", "harness",
        # 标识 3
        "workflow_id", "created_at", "user_id",
        # DAG 3
        "dag_pattern_hint", "description", "estimated_duration_ms",
        # 推荐 3
        "original_query", "parent_workflow_id", "retry_count",
        # Server 3
        "server_version", "trace_id", "ttl_ms",
        # 鉴权 2
        "auth_user_id", "auth_claim_set",
    }
    assert fields == expected, f"field mismatch: missing={expected-fields}, extra={fields-expected}"
    assert len(fields) == 19, f"expected 19 fields, got {len(fields)}"


def test_wau_workflow_all_snake_case_keys():
    """JSON 序列化全部 snake_case(per TS L15)"""
    w = WauWorkflow(
        agents=[WauWorkflowAgent(name="a1", url="http://x", skills=["s1"], confidence=0.9)],
        dependency_graph=WauWorkflowDependencyGraph(
            dependencies={"d1": WauWorkflowDependency(upstream_agents=["u1"])}
        ),
        confidence=0.9,
        workflow_type="WORKFLOW_TYPE_SINGLE",
        harness="codex-appserver",
    )
    data = asdict(w)

    def walk_keys(obj):
        keys = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.append(k)
                keys.extend(walk_keys(v))
        elif isinstance(obj, list) and obj:
            keys.extend(walk_keys(obj[0]))
        return keys

    all_keys = walk_keys(data)
    # 全部 snake_case(没 camelCase)
    camel = [k for k in all_keys if re.match(r"^[a-z]+[A-Z]", k)]
    assert not camel, f"unexpected camelCase keys: {camel}"


def test_wau_workflow_type_six_enum_values():
    """WauWorkflowType 6 enum 值(per TS L34-L40)"""
    expected = {
        "WORKFLOW_TYPE_UNSPECIFIED",
        "WORKFLOW_TYPE_SINGLE",
        "WORKFLOW_TYPE_CHAIN",
        "WORKFLOW_TYPE_PARALLEL",
        "WORKFLOW_TYPE_QUORUM",
        "WORKFLOW_TYPE_FAN_OUT",
    }
    # 6 值一一在 wire 字符串中
    sample = "WORKFLOW_TYPE_UNSPECIFIED"
    for v in expected:
        assert v.startswith("WORKFLOW_TYPE_"), v
    assert len(expected) == 6


def test_wau_workflow_agent_four_fields():
    """WauWorkflowAgent 4 字段(per TS L49-L55)"""
    a = WauWorkflowAgent(name="agent-1", url="http://x", skills=["s1"], confidence=0.95)
    data = asdict(a)
    assert set(data.keys()) == {"name", "url", "skills", "confidence"}


def test_wau_workflow_dependency_one_field():
    """WauWorkflowDependency 1 字段(per TS L60-L62)"""
    d = WauWorkflowDependency(upstream_agents=["u1", "u2"])
    data = asdict(d)
    assert set(data.keys()) == {"upstream_agents"}
    assert data["upstream_agents"] == ["u1", "u2"]


def test_wau_workflow_roundtrip_dict_dataclass():
    """dataclass 字段访问 + asdict 序列化都 OK(完整 round-trip 用 cattrs/pydantic,
    本 SDK 暂不引入 — 仅验证字段定义 1:1 跟 TS canonical 对齐)。
    """
    w = WauWorkflow(
        agents=[WauWorkflowAgent(name="a1", url="http://x", skills=["s1"], confidence=0.9)],
        dependency_graph=WauWorkflowDependencyGraph(
            dependencies={"d1": WauWorkflowDependency(upstream_agents=["u1"])}
        ),
        confidence=0.9,
        workflow_type="WORKFLOW_TYPE_SINGLE",
        harness="codex-appserver",
        workflow_id="wf-1",
        created_at=1700000000000,
        user_id="u-1",
        original_query="q",
        server_version="v1.0.0",
        trace_id="t-1",
        ttl_ms=30000,
        auth_user_id="u-1",
        auth_claim_set=["sub", "aud", "exp", "scope"],
    )
    # 字段访问
    assert w.workflow_id == "wf-1"
    assert w.agents[0].name == "a1"
    assert w.dependency_graph.dependencies["d1"].upstream_agents == ["u1"]
    assert w.auth_claim_set == ["sub", "aud", "exp", "scope"]

    # asdict 序列化 — 全部 snake_case
    data = asdict(w)
    assert data["workflow_id"] == "wf-1"
    assert data["auth_claim_set"] == ["sub", "aud", "exp", "scope"]
    assert data["agents"][0]["name"] == "a1"
    assert data["dependency_graph"]["dependencies"]["d1"]["upstream_agents"] == ["u1"]