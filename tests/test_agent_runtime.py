"""AgentRuntimeService 单测 — v1.3.1 M11 P2(2026-07-07)

覆盖范围(11 tests):
  - run_agent: success / empty prompt / 4xx / 5xx / JSON-RPC error / network err
  - load_skill: success / 404 not found / empty user_id
  - list_skills: success with universe filter / empty list
  - register_agent: success / 409 conflict

用 respx mock HTTP,无外部依赖,CI 友好。
"""

from __future__ import annotations

import httpx
import pytest
import respx

import wau_sdk
from wau_sdk import (
    Client,
    ClientOptions,
    LoadSkillRequest,
    LoadSkillResponse,
    RegisterAgentManifest,
    RetryConfig,
    CircuitConfig,
    RunAgentRequest,
    RunAgentResponse,
    Skill,
    SkillListResponse,
)


WAU_AGENT_URL = "http://mock-wau-agent:19408"
WAU_REGISTRY_URL = "http://mock-wau-registry:18401"


def _client() -> Client:
    return wau_sdk.Client(
        "http://mock-kernel:18400",
        ClientOptions(
            retry=RetryConfig(max_retries=0),
            circuit=CircuitConfig(enabled=False),
        ),
    )


@pytest.fixture
def client() -> Client:
    c = _client()
    # Override internal httpx endpoints (agent_runtime._http / _wau_agent_url)
    c.agent_runtime._wau_agent_url = WAU_AGENT_URL
    c.agent_runtime._wau_registry_url = WAU_REGISTRY_URL
    yield c
    c.close()


# ============================================================
# run_agent — JSON-RPC over HTTP POST /rpc
# ============================================================


def test_run_agent_success(client: Client) -> None:
    with respx.mock(base_url=WAU_AGENT_URL) as router:
        route = router.post("/rpc").mock(
            return_value=httpx.Response(200, json={
                "id": 1,
                "result": {
                    "Response": "你好,这是 hermes 生成的回复",
                    "ContextID": "ctx-abc-123",
                    "Provider": "deepseek-v4-flash",
                    "TokensUsed": 42,
                    "ElapsedMs": 150,
                },
            })
        )
        resp = client.agent_runtime.run_agent(
            RunAgentRequest(
                user_id="user-001",
                bot_id="bot-alpha",
                prompt="你好,请介绍一下你自己",
            )
        )
    assert isinstance(resp, RunAgentResponse)
    assert resp.response.startswith("你好")
    assert resp.context_id == "ctx-abc-123"
    assert resp.provider == "deepseek-v4-flash"
    assert resp.tokens_used == 42
    assert resp.elapsed_ms == 150
    assert route.called


def test_run_agent_empty_user_id(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="user_id required"):
        client.agent_runtime.run_agent(
            RunAgentRequest(user_id="", bot_id="bot-1", prompt="hello")
        )


def test_run_agent_empty_bot_id(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="bot_id required"):
        client.agent_runtime.run_agent(
            RunAgentRequest(user_id="u-1", bot_id="", prompt="hello")
        )


def test_run_agent_empty_prompt(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="prompt required"):
        client.agent_runtime.run_agent(
            RunAgentRequest(user_id="u-1", bot_id="b-1", prompt="")
        )


def test_run_agent_jsonrpc_error(client: Client) -> None:
    with respx.mock(base_url=WAU_AGENT_URL) as router:
        router.post("/rpc").mock(
            return_value=httpx.Response(200, json={
                "id": 1,
                "error": {"code": -32601, "message": "Method not found"},
            })
        )
        with pytest.raises(wau_sdk.APIError, match="JSON-RPC error -32601"):
            client.agent_runtime.run_agent(
                RunAgentRequest(user_id="u-1", bot_id="b-1", prompt="hi")
            )


def test_run_agent_http_404(client: Client) -> None:
    with respx.mock(base_url=WAU_AGENT_URL) as router:
        router.post("/rpc").mock(return_value=httpx.Response(404, text="not found"))
        with pytest.raises(wau_sdk.NotFoundError):
            client.agent_runtime.run_agent(
                RunAgentRequest(user_id="u-1", bot_id="b-1", prompt="hi")
            )


def test_run_agent_network_error(client: Client) -> None:
    with respx.mock(base_url=WAU_AGENT_URL) as router:
        router.post("/rpc").mock(side_effect=httpx.ConnectError("connection refused"))
        with pytest.raises(wau_sdk.APIError, match="HTTP error"):
            client.agent_runtime.run_agent(
                RunAgentRequest(user_id="u-1", bot_id="b-1", prompt="hi")
            )


# ============================================================
# load_skill — POST /registry/skills/load
# ============================================================


def test_load_skill_success(client: Client) -> None:
    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        route = router.post("/registry/skills/load").mock(
            return_value=httpx.Response(200, json={
                "skill_name": "weather",
                "loaded": True,
                "entrypoint": "skills/weather/main.py",
                "parameters": {"city": "Beijing"},
                "message": "loaded into user-001 skill pool",
            })
        )
        resp = client.agent_runtime.load_skill(
            LoadSkillRequest(user_id="user-001", skill_name="weather", bot_id="bot-1")
        )
    assert isinstance(resp, LoadSkillResponse)
    assert resp.loaded is True
    assert resp.skill_name == "weather"
    assert resp.entrypoint == "skills/weather/main.py"
    assert resp.parameters == {"city": "Beijing"}
    assert route.called


def test_load_skill_404_not_found(client: Client) -> None:
    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        router.post("/registry/skills/load").mock(
            return_value=httpx.Response(404, text="skill not found: nonexistent")
        )
        with pytest.raises(wau_sdk.NotFoundError):
            client.agent_runtime.load_skill(
                LoadSkillRequest(user_id="u-1", skill_name="nonexistent")
            )


def test_load_skill_empty_user_id(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="user_id required"):
        client.agent_runtime.load_skill(LoadSkillRequest(user_id="", skill_name="weather"))


# ============================================================
# list_skills — GET /registry/skills
# ============================================================


def test_list_skills_with_universe_filter(client: Client) -> None:
    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        route = router.get("/registry/skills", params={"universe": "default"}).mock(
            return_value=httpx.Response(200, json={
                "skills": [
                    {"name": "weather", "version": "0.1.0", "is_builtin": True},
                    {"name": "reminder", "version": "0.2.1", "is_builtin": True},
                ],
                "total": 2,
            })
        )
        resp = client.agent_runtime.list_skills(universe="default")
    assert isinstance(resp, SkillListResponse)
    assert len(resp.skills) == 2
    assert resp.skills[0].name == "weather"
    assert resp.skills[0].is_builtin is True
    assert resp.total == 2
    assert route.called


def test_list_skills_empty(client: Client) -> None:
    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        router.get("/registry/skills").mock(
            return_value=httpx.Response(200, json={"skills": [], "total": 0})
        )
        resp = client.agent_runtime.list_skills()
    assert resp.skills == []
    assert resp.total == 0


# ============================================================
# register_agent — POST /registry/agents(D60 兼容老契约)
# ============================================================


def test_register_agent_success(client: Client) -> None:
    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        route = router.post("/registry/agents").mock(
            return_value=httpx.Response(200, json={"name": "hermes-universal"})
        )
        client.agent_runtime.register_agent(
            RegisterAgentManifest(
                name="hermes-universal",
                description="WAU default agent",
                version="0.1.0",
                entrypoint="hermes_universal/main.py",
                skills=["general", "translation"],
                universes=["default"],
            )
        )
    assert route.called


def test_register_agent_empty_name(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="name required"):
        client.agent_runtime.register_agent(RegisterAgentManifest(name=""))


# ============================================================
# publish_agent — POST /registry/skills/publish (M11 P4 / I 子项)
# ============================================================


def test_publish_agent_success(client: Client, tmp_path) -> None:
    """publish_agent posts multipart(manifest JSON + tarball) and decodes response."""
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"fake-tarball-bytes")

    with respx.mock(base_url=WAU_REGISTRY_URL) as router:
        route = router.post("/registry/skills/publish").mock(
            return_value=httpx.Response(
                201,
                json={
                    "name": "weather-bot",
                    "version": "0.1.0",
                    "entrypoint": "skills/weather/main.py",
                    "bundle_size": 18,
                    "bundle_sha": "abc123",
                },
            )
        )
        resp = client.agent_runtime.publish_agent(
            RegisterAgentManifest(
                name="weather-bot",
                version="0.1.0",
                entrypoint="skills/weather/main.py",
            ),
            str(bundle_path),
        )
    assert route.called
    assert resp.name == "weather-bot"
    assert resp.version == "0.1.0"
    assert resp.bundle_size == 18
    assert resp.bundle_sha == "abc123"


def test_publish_agent_empty_name(client: Client, tmp_path) -> None:
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"x")
    with pytest.raises(wau_sdk.BadRequestError, match="manifest.name required"):
        client.agent_runtime.publish_agent(
            RegisterAgentManifest(name=""), str(bundle_path)
        )


def test_publish_agent_missing_bundle_path(client: Client) -> None:
    with pytest.raises(wau_sdk.BadRequestError, match="bundle_path required"):
        client.agent_runtime.publish_agent(
            RegisterAgentManifest(name="x", entrypoint="main.py"), ""
        )


def test_publish_agent_bad_path(client: Client) -> None:
    with pytest.raises(wau_sdk.APIError, match="read bundle"):
        client.agent_runtime.publish_agent(
            RegisterAgentManifest(name="x", entrypoint="main.py"),
            "/nonexistent/path.tar.gz",
        )


# ============================================================
# DTO 完整性测试
# ============================================================


def test_dto_construction() -> None:
    """所有 DTO 字段可构造 + 默认值生效"""
    # RunAgentRequest defaults
    r = RunAgentRequest(user_id="u", bot_id="b", prompt="p")
    assert r.context_id == ""
    assert r.timeout_sec == 30

    # Skill defaults
    s = Skill(name="weather")
    assert s.version == "0.1.0"
    assert s.universe == "default"
    assert s.parameters == {}
    assert s.is_builtin is False

    # LoadSkillRequest defaults
    lsr = LoadSkillRequest(user_id="u", skill_name="s")
    assert lsr.bot_id == ""
    assert lsr.install is True

    # RegisterAgentManifest defaults
    m = RegisterAgentManifest(name="agent-1")
    assert m.version == "0.1.0"
    assert m.skills == []
    assert m.universes == []