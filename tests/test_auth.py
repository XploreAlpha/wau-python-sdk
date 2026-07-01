"""Auth 单测 — HS256 JWT 签发 + exp + jti 唯一性"""

from __future__ import annotations

import time

import jwt
import pytest

from wau_sdk._auth import Signer
from wau_sdk._options import AuthConfig, Role

TEST_SECRET = b"test-secret-32-bytes-long-xxxxx"


# auth_builder 统一构造测试 AuthConfig,避免每个 case 重复 tenant_id/subject 字段。
# 注意:tenant_id 是必填(per Stage 3.1 #1 修复),空字符串会被 AuthConfig.__post_init__ 拒。
def auth_builder(**overrides) -> AuthConfig:
    base = {"agent_name": "test", "tenant_id": "test-tenant", "shared_secret": TEST_SECRET}
    base.update(overrides)
    return AuthConfig(**base)


def test_signer_empty_secret_raises() -> None:
    with pytest.raises(ValueError, match="shared_secret"):
        Signer(auth_builder(shared_secret=b""))


def test_signer_empty_agent_name_raises() -> None:
    with pytest.raises(ValueError, match="agent_name"):
        Signer(auth_builder(agent_name=""))


# test_signer_empty_tenant_id_raises — Stage 3.1 #1 新增(2026-07-01)
#
# wau-edge Claims 必填 tenant_id(per wau-edge/internal/auth/jwt.go:96-98)。
# SDK 必须强制租户非空,否则下游永远 401。
def test_signer_empty_tenant_id_raises() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        Signer(auth_builder(tenant_id=""))


def test_signer_default_role_is_external_agent() -> None:
    s = Signer(auth_builder())
    assert s.role == Role.EXTERNAL_AGENT.value


def test_signer_custom_role() -> None:
    s = Signer(auth_builder(agent_name="kernel", role=Role.KERNEL_CORE))
    assert s.role == "kernel_core"


# test_signer_subject_defaults_to_agent_name — Stage 3.1 #1 新增
def test_signer_subject_defaults_to_agent_name() -> None:
    s = Signer(auth_builder(agent_name="my-agent"))
    assert s._subject == "my-agent"  # noqa: SLF001 — 内部字段,测试可见


# test_signer_custom_subject — Stage 3.1 #1 新增
def test_signer_custom_subject() -> None:
    s = Signer(auth_builder(agent_name="agent-x", subject="user-y"))
    assert s._subject == "user-y"  # noqa: SLF001


def test_signer_sign_returns_3_segment_jwt() -> None:
    s = Signer(auth_builder())
    tok = s.sign()
    assert len(tok.split(".")) == 3  # header.payload.signature


# test_signer_sign_jwt_decodable_with_secret — Stage 3.1 #1 扩展,加 tenant_id / sub 校验
def test_signer_sign_jwt_decodable_with_secret() -> None:
    s = Signer(auth_builder(agent_name="test-agent", tenant_id="tenant-42", subject="user-7"))
    tok = s.sign()
    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    # Stage 3.1 #1 修复后:wau-edge Claims 必填 tenant_id + sub 对齐 Subject
    for k in ("agent", "role", "sub", "tenant_id", "iat", "exp", "jti"):
        assert k in decoded, f"JWT 缺字段 {k!r}"
    assert decoded["agent"] == "test-agent"
    assert decoded["role"] == "external_agent"
    assert decoded["tenant_id"] == "tenant-42"
    assert decoded["sub"] == "user-7"


def test_signer_sign_5_min_expiry() -> None:
    s = Signer(auth_builder())
    before = int(time.time())
    tok = s.sign()
    after = int(time.time())

    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    iat = decoded["iat"]
    exp = decoded["exp"]

    assert before <= iat <= after
    assert exp - iat == 300  # 5 min


def test_signer_sign_custom_ttl() -> None:
    s = Signer(auth_builder())
    tok = s.sign(ttl_seconds=60)
    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    assert decoded["exp"] - decoded["iat"] == 60


def test_signer_sign_jti_uniqueness() -> None:
    s = Signer(auth_builder())
    jtis = set()
    for _ in range(100):
        tok = s.sign()
        decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
        jti = decoded["jti"]
        assert jti not in jtis, "JTI 重复!"
        jtis.add(jti)


def test_signer_sign_hs256_alg() -> None:
    s = Signer(auth_builder())
    tok = s.sign()
    # 解析 header,验证 alg = HS256
    import base64
    import json

    header_b64 = tok.split(".")[0]
    # base64url padding
    padding = 4 - len(header_b64) % 4
    header_b64_padded = header_b64 + "=" * padding
    header = json.loads(base64.urlsafe_b64decode(header_b64_padded))
    assert header["alg"] == "HS256"
    assert header["typ"] == "JWT"


def test_signer_sign_wrong_secret_fails_decode() -> None:
    s1 = Signer(AuthConfig(
        agent_name="test", tenant_id="t1",
        shared_secret=b"secret-1",
    ))
    s2 = Signer(AuthConfig(
        agent_name="test", tenant_id="t1",
        shared_secret=b"secret-2-different",
    ))
    tok = s1.sign()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(tok, b"secret-2-different", algorithms=["HS256"])
