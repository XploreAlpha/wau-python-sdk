"""v0.8.0 M3-2B Universe Labels 校验函数测试

跟 afp-protocol + wau-go-sdk universe_labels_test 语义对齐
"""

from __future__ import annotations

from wau_sdk import (
    Agent,
    AgentRegisterRequest,
    LabelsValidationResult,
    RESERVED_UNIVERSE_LABEL_KEYS,
    is_reserved_label_key,
    log_labels_validation,
    validate_universe_labels,
)


# =============================================================================
# backward compat
# =============================================================================


def test_validate_universe_labels_none():
    r = validate_universe_labels(None)
    assert r.ok is True
    assert r.warnings == []
    assert r.errors == []


def test_validate_universe_labels_empty_dict():
    r = validate_universe_labels({})
    assert r.ok is True
    assert r.warnings == []


# =============================================================================
# 6 reserved labels
# =============================================================================


def test_reserved_region_free_string():
    r = validate_universe_labels({"region": "cn-shanghai"})
    assert r.ok is True
    assert r.warnings == []


def test_reserved_gpu_enum():
    for v in ["true", "false"]:
        r = validate_universe_labels({"gpu": v})
        assert r.ok is True
        assert r.warnings == [], f"gpu={v} should be OK"

    r = validate_universe_labels({"gpu": "yes"})
    assert r.ok is True
    assert len(r.warnings) == 1
    assert "not in allowed values" in r.warnings[0]


def test_reserved_gpu_empty():
    r = validate_universe_labels({"gpu": ""})
    assert r.ok is True
    assert len(r.warnings) == 1
    assert "empty value" in r.warnings[0]


def test_reserved_tier_enum():
    for v in ["low", "medium", "high-performance"]:
        r = validate_universe_labels({"tier": v})
        assert r.ok is True
        assert r.warnings == [], f"tier={v} should be OK"

    r = validate_universe_labels({"tier": "ultra"})
    assert len(r.warnings) == 1


def test_reserved_security_level():
    r = validate_universe_labels({"security_level": "trusted"})
    assert r.ok is True
    assert r.warnings == []

    r = validate_universe_labels({"security_level": "invalid"})
    assert len(r.warnings) == 1
    assert "not in allowed values" in r.warnings[0]


def test_reserved_load():
    for v in ["idle", "low", "medium", "high", "overloaded"]:
        r = validate_universe_labels({"load": v})
        assert r.ok is True
        assert r.warnings == [], f"load={v} should be OK"


def test_reserved_universe_role():
    r = validate_universe_labels({"universe_role": "compute-pool"})
    assert r.ok is True
    assert r.warnings == []

    r = validate_universe_labels({"universe_role": "invalid"})
    assert len(r.warnings) == 1


# =============================================================================
# 自由 labels 命名规范
# =============================================================================


def test_free_label_snake_case_ok():
    r = validate_universe_labels({"department": "healthcare"})
    assert r.ok is True
    assert r.warnings == []


def test_free_label_kebab_case_warns():
    r = validate_universe_labels({"cost-center": "eng-001"})
    assert r.ok is True
    assert len(r.warnings) == 1
    assert "cost_center" in r.warnings[0]


def test_free_label_camel_case_warns():
    r = validate_universe_labels({"myLabel": "value"})
    assert r.ok is True
    assert len(r.warnings) == 1
    assert "my_label" in r.warnings[0]


def test_free_label_empty_value_warns():
    r = validate_universe_labels({"department": ""})
    assert r.ok is True
    assert len(r.warnings) == 1
    assert "empty value" in r.warnings[0]


# =============================================================================
# 多 labels 组合
# =============================================================================


def test_multiple_reserved_labels_ok():
    r = validate_universe_labels({
        "region": "cn-shanghai",
        "gpu": "true",
        "tier": "high-performance",
        "load": "idle",
    })
    assert r.ok is True
    assert r.warnings == []


def test_mixed_warnings():
    r = validate_universe_labels({
        "region": "cn-shanghai",   # OK
        "tier": "ultra",            # warning
        "department": "rnd",        # OK
        "non-standard": "x",        # warning
        "myCustomLabel": "y",       # warning
    })
    assert r.ok is True
    assert len(r.warnings) == 3


# =============================================================================
# 白名单常量完整性
# =============================================================================


def test_reserved_label_keys_6():
    expected = {"region", "gpu", "tier", "security_level", "load", "universe_role"}
    assert set(RESERVED_UNIVERSE_LABEL_KEYS) == expected


def test_is_reserved_label_key():
    assert is_reserved_label_key("region") is True
    assert is_reserved_label_key("tier") is True
    assert is_reserved_label_key("department") is False
    assert is_reserved_label_key("myCustomLabel") is False


# =============================================================================
# Agent + AgentRegisterRequest dataclass 集成测试
# =============================================================================


def test_agent_universe_labels_field():
    # 老 client 不传 → 空 dict
    a = Agent(name="test")
    assert a.universe_labels == {}

    # 新 client 传 dict
    a2 = Agent(
        name="test2",
        universe_labels={"region": "cn-shanghai", "gpu": "true"},
    )
    assert a2.universe_labels["region"] == "cn-shanghai"
    assert a2.universe_labels["gpu"] == "true"


def test_agent_register_request_universe_labels_field():
    req = AgentRegisterRequest(
        name="agent1",
        url="https://example.com",
        universes=["universe-a"],
        universe_labels={"tier": "high-performance"},
    )
    assert req.universe_labels["tier"] == "high-performance"


# =============================================================================
# log_labels_validation 便捷方法(只验证不抛 + 不抛异常)
# =============================================================================


def test_log_labels_validation_no_log(caplog):
    r = LabelsValidationResult(ok=True)
    log_labels_validation(r, "test")
    # 不输出日志


def test_log_labels_validation_with_warnings(caplog):
    r = LabelsValidationResult(
        ok=True,
        warnings=["warn1", "warn2"],
    )
    with caplog.at_level("WARNING"):
        log_labels_validation(r, "test")
    assert any("warn1" in rec.message for rec in caplog.records)


def test_log_labels_validation_with_errors(caplog):
    r = LabelsValidationResult(
        ok=False,
        errors=["err1"],
    )
    with caplog.at_level("ERROR"):
        log_labels_validation(r, "test")
    assert any("err1" in rec.message for rec in caplog.records)
