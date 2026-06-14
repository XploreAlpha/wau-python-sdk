"""Auth 单测 — HS256 JWT 签发 + exp + jti 唯一性"""

from __future__ import annotations

import time

import jwt
import pytest

from wau_sdk._auth import Signer
from wau_sdk._options import AuthConfig, Role

TEST_SECRET = b"test-secret-32-bytes-long-xxxxx"


def test_signer_empty_secret_raises() -> None:
    with pytest.raises(ValueError, match="shared_secret"):
        Signer(AuthConfig(agent_name="a", shared_secret=b""))


def test_signer_empty_agent_name_raises() -> None:
    with pytest.raises(ValueError, match="agent_name"):
        Signer(AuthConfig(agent_name="", shared_secret=TEST_SECRET))


def test_signer_default_role_is_external_agent() -> None:
    s = Signer(AuthConfig(agent_name="a", shared_secret=TEST_SECRET))
    assert s.role == Role.EXTERNAL_AGENT.value


def test_signer_custom_role() -> None:
    s = Signer(AuthConfig(agent_name="a", shared_secret=TEST_SECRET, role=Role.KERNEL_CORE))
    assert s.role == "kernel_core"


def test_signer_sign_returns_3_segment_jwt() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
    tok = s.sign()
    assert len(tok.split(".")) == 3  # header.payload.signature


def test_signer_sign_jwt_decodable_with_secret() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
    tok = s.sign()
    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    assert decoded["agent"] == "test"
    assert decoded["role"] == "external_agent"
    assert "iat" in decoded
    assert "exp" in decoded
    assert "jti" in decoded


def test_signer_sign_5_min_expiry() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
    before = int(time.time())
    tok = s.sign()
    after = int(time.time())

    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    iat = decoded["iat"]
    exp = decoded["exp"]

    assert before <= iat <= after
    assert exp - iat == 300  # 5 min


def test_signer_sign_custom_ttl() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
    tok = s.sign(ttl_seconds=60)
    decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    assert decoded["exp"] - decoded["iat"] == 60


def test_signer_sign_jti_uniqueness() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
    jtis = set()
    for _ in range(100):
        tok = s.sign()
        decoded = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
        jti = decoded["jti"]
        assert jti not in jtis, "JTI 重复!"
        jtis.add(jti)


def test_signer_sign_hs256_alg() -> None:
    s = Signer(AuthConfig(agent_name="test", shared_secret=TEST_SECRET))
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
    s1 = Signer(AuthConfig(agent_name="test", shared_secret=b"secret-1"))
    s2 = Signer(AuthConfig(agent_name="test", shared_secret=b"secret-2-different"))
    tok = s1.sign()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(tok, b"secret-2-different", algorithms=["HS256"])
