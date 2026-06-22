"""v0.8.0 M3-2B — Universe Labels 校验

跟 wau-go-sdk universe_labels.go 语义对齐
跟 WAU-core-kernel internal/registry/universe_labels.go 语义对齐
跟 afp-protocol 端 src/universe_labels.ts 语义对齐

关键约束(per v0.8.0 M3 B 计划决策 2 软警告):
   - SDK 端只预校验(减少 round-trip),server 端是 source of truth
   - 软警告不阻断,只 logging.warning
   - 老 client 不传 labels → None/空 dict,无 warning
   - 4 SDK 漂移风险:kernel 公开 ReservedLabelKeys 常量作 source of truth
     (本文件直接复制,未来可改成代码生成)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

# =============================================================================
# 6 个 reserved labels 白名单
# =============================================================================
#
# 跟 WAU-core-kernel + wau-go-sdk + afp-protocol 1:1
# server 是 source of truth,SDK 端复制(漂移风险 M5 联调时校对)

_RESERVED_LABELS_ALL_VALUES: dict[str, set[str]] = {
    "region": set(),  # 自由字符串
    "gpu": {"true", "false"},
    "tier": {"low", "medium", "high-performance"},
    "security_level": {"trusted", "untrusted"},
    "load": {"idle", "low", "medium", "high", "overloaded"},
    "universe_role": {"business", "compute-pool"},
}

_RESERVED_LABEL_KEYS: set[str] = set(_RESERVED_LABELS_ALL_VALUES.keys())

# 公开常量(供 caller 引用,避免各自维护漂移)
RESERVED_UNIVERSE_LABEL_KEYS: list[str] = sorted(_RESERVED_LABEL_KEYS)

_SNAKE_CASE_REGEX = re.compile(r"^[a-z][a-z0-9_]*$")


def is_reserved_label_key(key: str) -> bool:
    """检查 key 是否在 reserved 白名单"""
    return key in _RESERVED_LABEL_KEYS


# =============================================================================
# 校验结果类型
# =============================================================================


@dataclass
class LabelsValidationResult:
    """校验结果(跟 kernel 端 + AFP 端字段 1:1)"""
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# =============================================================================
# 核心校验函数
# =============================================================================


def validate_universe_labels(
    labels: dict[str, str] | None,
) -> LabelsValidationResult:
    """校验单个 labels map

    永远不抛,返 LabelsValidationResult
    SDK 端调用方应检查 r.ok,warnings 走 logging.warning,errors 走 logging.error
    """
    result = LabelsValidationResult()

    if not labels:
        return result

    for key, value in labels.items():
        # 自由 label key 命名 warning
        if key not in _RESERVED_LABEL_KEYS and not _SNAKE_CASE_REGEX.match(key):
            result.warnings.append(
                f'free label "{key}" should be snake_case (e.g. "{_to_snake_case(key)}")'
            )

        # reserved label 校验
        if key in _RESERVED_LABEL_KEYS:
            allowed = _RESERVED_LABELS_ALL_VALUES[key]
            if value == "":
                result.warnings.append(
                    f'reserved label "{key}" has empty value (consider removing or setting valid value)'
                )
            elif allowed and value not in allowed:
                sorted_allowed = ", ".join(sorted(allowed))
                result.warnings.append(
                    f'reserved label "{key}"="{value}" not in allowed values [{sorted_allowed}]'
                )
            continue

        # 自由 label 空 value warning
        if value == "":
            result.warnings.append(f'free label "{key}" has empty value')

    return result


def log_labels_validation(
    result: LabelsValidationResult, context: str = "register"
) -> None:
    """把校验结果走 logging(SDK 默认 logger)

       - warnings → logging.warning(前缀 [WAU SDK warn])
       - errors → logging.error(前缀 [WAU SDK error])

    调用方应在 RegisterCard / RegisterAgent / RegisterPeer 前调
    """
    if result.ok and not result.warnings and not result.errors:
        return
    for w in result.warnings:
        logging.warning("[WAU SDK %s warn] %s", context, w)
    for e in result.errors:
        logging.error("[WAU SDK %s error] %s", context, e)


# =============================================================================
# 内部工具
# =============================================================================


def _to_snake_case(s: str) -> str:
    """camelCase / kebab-case → snake_case"""
    out: list[str] = []
    for i, ch in enumerate(s):
        if i > 0 and ch.isupper():
            out.append("_")
        if ch == "-" or ch == " ":
            out.append("_")
        else:
            out.append(ch.lower())
    return "".join(out)
