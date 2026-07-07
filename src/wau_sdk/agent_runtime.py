"""AgentRuntimeService — v1.3.1 M11 P2 新增(2026-07-07)

调用 wau-agent 的 HTTP JSON-RPC gateway(端口 19408 /rpc)
+ wau-registry HTTP REST(端口 18401 /registry/skills/*)

设计动机:
- wau-agent 暴露 3 endpoint:RunAgent RPC / SkillLoad REST / RegisterAgent REST
- wau-agent RunAgent 走 JSON-RPC over HTTP(POST /rpc body={method,params})
- wau-registry Skill 走 REST(per agentskills.io D69=A 拍板)
- RegisterAgent 走 wau-registry 老契约 /registry/agents(D60 兼容)

调用方(per M11 W4-W5 design + D67=B sidecar subprocess):
- C 端:telegram bot → wau-channel → wau-edge → wau-agent (RunAgent RPC)
- B 端:SDK caller → wau-registry (register_agent) → wau-agent 加载
- C 端装 skill:用户说"安装天气 skill" → wau-registry → wau-agent 加载

注意:本 service 内部用独立 httpx.Client(不走 _transport),
因为 wau-agent gateway 不是 REST 风格(JSON-RPC over HTTP),
跟 kernel/registry REST endpoint 协议不同。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx

from wau_sdk._errors import (
    APIError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from wau_sdk.types import (
    LoadSkillRequest,
    LoadSkillResponse,
    RegisterAgentManifest,
    RunAgentRequest,
    RunAgentResponse,
    Skill,
    SkillListResponse,
    SkillPublishResponse,  # v1.3.1 M11 P4 (I 子项)
)

__all__ = ["AgentRuntimeService", "AsyncAgentRuntimeService"]

logger = logging.getLogger("wau_sdk.agent_runtime")

# JSON-RPC 2.0 错误码(per wau-agent internal/rpc/gateway.go)
_JSONRPC_PARSE_ERROR = -32700
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_INTERNAL_ERROR = -32603

_HTTP_STATUS_MAP: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
}


class AgentRuntimeService:
    """同步 AgentRuntimeService — wau-agent 调用方(per M11 W4-W5,2026-07-07)"""

    def __init__(self, client: "Client") -> None:  # type: ignore[name-defined]  # noqa: F821
        # 配置两个 endpoint:
        #  - wau_agent_url  : wau-agent HTTP JSON-RPC gateway(默认 http://localhost:19408)
        #  - wau_registry_url : wau-registry HTTP(默认 http://localhost:18401) — Skill/Register
        # 通过 client.options.agent_runtime 覆盖(见 _options.py)
        opts = client.options
        self._wau_agent_url = getattr(opts, "wau_agent_url", "http://localhost:19408")
        self._wau_registry_url = getattr(opts, "wau_registry_url", "http://localhost:18401")
        self._timeout = float(getattr(opts, "timeout_sec", 30))
        self._client = client  # 持有引用,方便 __del__ 关 httpx

        # httpx client + id 计数器(per process 单调递增)
        self._http = httpx.Client(timeout=self._timeout)
        self._id_lock = threading.Lock()
        self._id_counter = 0

    def close(self) -> None:
        """关 httpx(per SDK 惯例,Client.close() 会调到这里)"""
        try:
            self._http.close()
        except Exception:  # pragma: no cover
            pass

    def _next_id(self) -> int:
        with self._id_lock:
            self._id_counter += 1
            return self._id_counter

    # ============================================================
    # RunAgent — 走 wau-agent JSON-RPC gateway(POST /rpc)
    # ============================================================

    def run_agent(self, req: RunAgentRequest) -> RunAgentResponse:
        """RunAgent 同步调用 wau-agent gateway(per M11 W4-W5 / D75=B pool)

        入参 RunAgentRequest 字段:
          user_id, bot_id(必填)
          prompt(必填)
          context_id(可选,空 = 新会话)
          timeout_sec(默认 30s)
        出参 RunAgentResponse 字段:
          response, context_id, provider, tokens_used, elapsed_ms
        """
        if not req.user_id:
            raise BadRequestError("run_agent: user_id required")
        if not req.bot_id:
            raise BadRequestError("run_agent: bot_id required")
        if not req.prompt:
            raise BadRequestError("run_agent: prompt required")

        params: dict[str, Any] = {
            "UserID": req.user_id,
            "BotID": req.bot_id,
            "Prompt": req.prompt,
            "ContextID": req.context_id,
            "TimeoutSec": req.timeout_sec if req.timeout_sec > 0 else 30,
        }
        body = {
            "id": self._next_id(),
            "method": "WauAgent.RunAgent",
            "params": params,
        }
        url = self._wau_agent_url.rstrip("/") + "/rpc"
        try:
            resp = self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"run_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"run_agent: HTTP {resp.status_code}: {resp.text}")

        # wau-agent JSON-RPC 200 OK 也有 error 字段(RPC 协议错误)
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise APIError(f"run_agent: non-JSON response: {resp.text}") from exc

        if "error" in data:
            err = data["error"]
            raise APIError(
                f"run_agent: JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}"
            )
        result = data.get("result", {})
        return RunAgentResponse(
            response=str(result.get("Response", "")),
            context_id=str(result.get("ContextID", "")),
            provider=str(result.get("Provider", "")),
            tokens_used=int(result.get("TokensUsed", 0) or 0),
            elapsed_ms=int(result.get("ElapsedMs", 0) or 0),
        )

    # ============================================================
    # Skill — 走 wau-registry HTTP REST(/registry/skills/*)
    # ============================================================

    def load_skill(self, req: LoadSkillRequest) -> LoadSkillResponse:
        """POST /registry/skills/load(per D69=A agentskills.io load spec)

        入参 LoadSkillRequest:
          user_id(必填) — C 端 user ID
          skill_name(必填)
          bot_id(可选) — 绑到具体 bot(空 = user 全 bot)
          install(默认 True) — True=持久化,False=临时加载

        出参 LoadSkillResponse:
          skill_name, loaded(bool), entrypoint, parameters(dict), message
        """
        if not req.user_id:
            raise BadRequestError("load_skill: user_id required")
        if not req.skill_name:
            raise BadRequestError("load_skill: skill_name required")

        url = self._wau_registry_url.rstrip("/") + "/registry/skills/load"
        body = {
            "user_id": req.user_id,
            "skill_name": req.skill_name,
            "bot_id": req.bot_id,
            "install": req.install,
        }
        try:
            resp = self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"load_skill: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"load_skill: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        return LoadSkillResponse(
            skill_name=str(data.get("skill_name", req.skill_name)),
            loaded=bool(data.get("loaded", False)),
            entrypoint=str(data.get("entrypoint", "")),
            parameters=data.get("parameters", {}) or {},
            message=str(data.get("message", "")),
        )

    def list_skills(self, universe: str = "") -> SkillListResponse:
        """GET /registry/skills?universe=...

        入参 universe(可选)— 业务分组过滤
        出参 SkillListResponse.skills + total
        """
        url = self._wau_registry_url.rstrip("/") + "/registry/skills"
        params: dict[str, str] = {}
        if universe:
            params["universe"] = universe
        try:
            resp = self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise APIError(f"list_skills: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"list_skills: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        raw_skills = data.get("skills", []) or []
        skills = [Skill(**s) if isinstance(s, dict) else s for s in raw_skills]
        return SkillListResponse(skills=skills, total=int(data.get("total", len(skills))))

    # ============================================================
    # RegisterAgent — 走 wau-registry 老契约(/registry/agents, D60 兼容)
    # ============================================================

    def register_agent(self, manifest: RegisterAgentManifest) -> None:
        """POST /registry/agents(per D60 兼容老契约 + D69=A agentskills.io)

        入参 RegisterAgentManifest:
          name(必填)
          description, version, entrypoint, skills, universes, parameters, source_url
        出参:None(注册成功 204 No Content / 200 OK)
        """
        if not manifest.name:
            raise BadRequestError("register_agent: name required")

        url = self._wau_registry_url.rstrip("/") + "/registry/agents"
        body = {
            "name": manifest.name,
            "description": manifest.description,
            "version": manifest.version,
            "entrypoint": manifest.entrypoint,
            "skills": manifest.skills,
            "universes": manifest.universes,
            "parameters": manifest.parameters,
            "source_url": manifest.source_url,
        }
        try:
            resp = self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"register_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"register_agent: HTTP {resp.status_code}: {resp.text}")

    # ============================================================
    # publish_agent — 上架 skill bundle(per M11 P4 / I 子项,同步版)
    # ============================================================

    def publish_agent(
        self,
        manifest: RegisterAgentManifest,
        bundle_path: str,
    ) -> SkillPublishResponse:
        """POST /registry/skills/publish — multipart(manifest JSON + tarball)。

        详见 async 版 — 这是同步镜像。
        """
        if not manifest.name:
            raise BadRequestError("publish_agent: manifest.name required")
        if not bundle_path:
            raise BadRequestError("publish_agent: bundle_path required")

        try:
            with open(bundle_path, "rb") as f:
                bundle_bytes = f.read()
        except OSError as exc:
            raise APIError(f"publish_agent: read bundle {bundle_path}: {exc}") from exc

        url = self._wau_registry_url.rstrip("/") + "/registry/skills/publish"
        import json as _json

        files = {
            "manifest": ("manifest.json", _json.dumps({
                "name": manifest.name,
                "description": manifest.description,
                "version": manifest.version,
                "entrypoint": manifest.entrypoint,
                "skills": manifest.skills,
                "universes": manifest.universes,
                "parameters": manifest.parameters,
                "source_url": manifest.source_url,
            }).encode("utf-8"), "application/json"),
            "bundle": (manifest.name + ".tar.gz", bundle_bytes, "application/gzip"),
        }
        try:
            resp = self._http.post(url, files=files)
        except httpx.HTTPError as exc:
            raise APIError(f"publish_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"publish_agent: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        return SkillPublishResponse(
            name=data.get("name", manifest.name),
            version=data.get("version", manifest.version),
            entrypoint=data.get("entrypoint", manifest.entrypoint),
            bundle_size=int(data.get("bundle_size", len(bundle_bytes))),
            bundle_sha=data.get("bundle_sha", ""),
        )


class AsyncAgentRuntimeService:
    """异步 AgentRuntimeService(API 镜像同步版)"""

    def __init__(self, client: "AsyncClient") -> None:  # type: ignore[name-defined]  # noqa: F821
        opts = client.options
        self._wau_agent_url = getattr(opts, "wau_agent_url", "http://localhost:19408")
        self._wau_registry_url = getattr(opts, "wau_registry_url", "http://localhost:18401")
        self._timeout = float(getattr(opts, "timeout_sec", 30))

        self._http = httpx.AsyncClient(timeout=self._timeout)
        self._id_lock = threading.Lock()
        self._id_counter = 0

    async def close(self) -> None:
        try:
            await self._http.aclose()
        except Exception:  # pragma: no cover
            pass

    def _next_id(self) -> int:
        with self._id_lock:
            self._id_counter += 1
            return self._id_counter

    async def run_agent(self, req: RunAgentRequest) -> RunAgentResponse:
        if not req.user_id:
            raise BadRequestError("run_agent: user_id required")
        if not req.bot_id:
            raise BadRequestError("run_agent: bot_id required")
        if not req.prompt:
            raise BadRequestError("run_agent: prompt required")

        params: dict[str, Any] = {
            "UserID": req.user_id,
            "BotID": req.bot_id,
            "Prompt": req.prompt,
            "ContextID": req.context_id,
            "TimeoutSec": req.timeout_sec if req.timeout_sec > 0 else 30,
        }
        body = {
            "id": self._next_id(),
            "method": "WauAgent.RunAgent",
            "params": params,
        }
        url = self._wau_agent_url.rstrip("/") + "/rpc"
        try:
            resp = await self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"run_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"run_agent: HTTP {resp.status_code}: {resp.text}")

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise APIError(f"run_agent: non-JSON response: {resp.text}") from exc

        if "error" in data:
            err = data["error"]
            raise APIError(
                f"run_agent: JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}"
            )
        result = data.get("result", {})
        return RunAgentResponse(
            response=str(result.get("Response", "")),
            context_id=str(result.get("ContextID", "")),
            provider=str(result.get("Provider", "")),
            tokens_used=int(result.get("TokensUsed", 0) or 0),
            elapsed_ms=int(result.get("ElapsedMs", 0) or 0),
        )

    async def load_skill(self, req: LoadSkillRequest) -> LoadSkillResponse:
        if not req.user_id:
            raise BadRequestError("load_skill: user_id required")
        if not req.skill_name:
            raise BadRequestError("load_skill: skill_name required")

        url = self._wau_registry_url.rstrip("/") + "/registry/skills/load"
        body = {
            "user_id": req.user_id,
            "skill_name": req.skill_name,
            "bot_id": req.bot_id,
            "install": req.install,
        }
        try:
            resp = await self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"load_skill: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"load_skill: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        return LoadSkillResponse(
            skill_name=str(data.get("skill_name", req.skill_name)),
            loaded=bool(data.get("loaded", False)),
            entrypoint=str(data.get("entrypoint", "")),
            parameters=data.get("parameters", {}) or {},
            message=str(data.get("message", "")),
        )

    async def list_skills(self, universe: str = "") -> SkillListResponse:
        url = self._wau_registry_url.rstrip("/") + "/registry/skills"
        params: dict[str, str] = {}
        if universe:
            params["universe"] = universe
        try:
            resp = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise APIError(f"list_skills: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"list_skills: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        raw_skills = data.get("skills", []) or []
        skills = [Skill(**s) if isinstance(s, dict) else s for s in raw_skills]
        return SkillListResponse(skills=skills, total=int(data.get("total", len(skills))))

    async def register_agent(self, manifest: RegisterAgentManifest) -> None:
        if not manifest.name:
            raise BadRequestError("register_agent: name required")

        url = self._wau_registry_url.rstrip("/") + "/registry/agents"
        body = {
            "name": manifest.name,
            "description": manifest.description,
            "version": manifest.version,
            "entrypoint": manifest.entrypoint,
            "skills": manifest.skills,
            "universes": manifest.universes,
            "parameters": manifest.parameters,
            "source_url": manifest.source_url,
        }
        try:
            resp = await self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise APIError(f"register_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"register_agent: HTTP {resp.status_code}: {resp.text}")

    # ============================================================
    # publish_agent — 上架 skill bundle(per M11 P4 / I 子项)
    # ============================================================

    async def publish_agent(
        self,
        manifest: RegisterAgentManifest,
        bundle_path: str,
    ) -> SkillPublishResponse:
        """POST /registry/skills/publish — multipart(manifest JSON + tarball)。

        Args:
            manifest: RegisterAgentManifest(name/version/entrypoint 必填)
            bundle_path: 本地 tarball 路径(由 `wau-cli wau agent publish --from`
                打包生成)

        Returns:
            SkillPublishResponse — name/version/entrypoint/bundle_size/bundle_sha

        Raises:
            BadRequestError: manifest 字段缺失
            APIError: HTTP 错误 / 网络错
            NotFoundError: 路由不存在(registry 旧版本)
        """
        if not manifest.name:
            raise BadRequestError("publish_agent: manifest.name required")
        if not bundle_path:
            raise BadRequestError("publish_agent: bundle_path required")

        # Read bundle bytes.
        try:
            with open(bundle_path, "rb") as f:
                bundle_bytes = f.read()
        except OSError as exc:
            raise APIError(f"publish_agent: read bundle {bundle_path}: {exc}") from exc

        url = self._wau_registry_url.rstrip("/") + "/registry/skills/publish"
        # Build multipart payload: "manifest" (JSON file) + "bundle" (tarball).
        import json as _json

        files = {
            "manifest": ("manifest.json", _json.dumps({
                "name": manifest.name,
                "description": manifest.description,
                "version": manifest.version,
                "entrypoint": manifest.entrypoint,
                "skills": manifest.skills,
                "universes": manifest.universes,
                "parameters": manifest.parameters,
                "source_url": manifest.source_url,
            }).encode("utf-8"), "application/json"),
            "bundle": (manifest.name + ".tar.gz", bundle_bytes, "application/gzip"),
        }
        try:
            resp = await self._http.post(url, files=files)
        except httpx.HTTPError as exc:
            raise APIError(f"publish_agent: HTTP error: {exc}") from exc

        if resp.status_code in _HTTP_STATUS_MAP:
            cls = _HTTP_STATUS_MAP[resp.status_code]
            raise cls(f"publish_agent: HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        return SkillPublishResponse(
            name=data.get("name", manifest.name),
            version=data.get("version", manifest.version),
            entrypoint=data.get("entrypoint", manifest.entrypoint),
            bundle_size=int(data.get("bundle_size", len(bundle_bytes))),
            bundle_sha=data.get("bundle_sha", ""),
        )