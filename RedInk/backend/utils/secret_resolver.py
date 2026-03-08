"""Resolve API keys from provider config, env vars, or .claude/CLAUDE.md."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple


DEFAULT_ENV_NAMES = [
    "GLM_API_KEY",
    "ZHIPUAI_API_KEY",
    "OPENAI_API_KEY",
    "GLM_tokens",
]


def _normalize_secret_value(raw: object) -> str:
    value = str(raw or "").strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        value = value[1:-1].strip()
    return value


def _candidate_paths(project_root: Optional[Path] = None) -> list[Path]:
    roots: list[Path] = []
    if project_root is not None:
        roots.append(project_root)
    roots.append(Path(__file__).resolve().parents[2])  # .../RedInk
    roots.append(Path(__file__).resolve().parents[3])  # .../xhs_note
    dedup: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in dedup:
            dedup.append(resolved)
    return [root / ".claude" / "CLAUDE.md" for root in dedup]


def _iter_env_names(preferred_env_names: Optional[Iterable[str]] = None) -> list[str]:
    env_names: list[str] = []
    for name in preferred_env_names or []:
        normalized = str(name or "").strip()
        if normalized and normalized not in env_names:
            env_names.append(normalized)
    for name in DEFAULT_ENV_NAMES:
        if name not in env_names:
            env_names.append(name)
    return env_names


def _load_api_key_from_claude_md(
    env_names: list[str],
    project_root: Optional[Path] = None,
) -> Tuple[str, str]:
    if not env_names:
        return "", ""

    name_pattern = "|".join(re.escape(name) for name in env_names)
    pattern = re.compile(
        rf"^\s*(?:export\s+)?(?P<name>{name_pattern})\s*[:=]\s*(?P<value>.+?)\s*$"
    )

    for claude_md in _candidate_paths(project_root):
        if not claude_md.exists():
            continue
        for line in claude_md.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            key_value = _normalize_secret_value(match.group("value"))
            if key_value:
                return key_value, f"{claude_md}#{match.group('name')}"
    return "", ""


def resolve_api_key(
    configured_key: object = "",
    preferred_env_names: Optional[Iterable[str]] = None,
    project_root: Optional[Path] = None,
) -> Tuple[str, str]:
    """Resolve API key in priority: provider config -> env -> .claude/CLAUDE.md."""
    direct_key = _normalize_secret_value(configured_key)
    if direct_key:
        return direct_key, "provider_config.api_key"

    env_names = _iter_env_names(preferred_env_names)
    for env_name in env_names:
        value = _normalize_secret_value(os.getenv(env_name, ""))
        if value:
            return value, f"env:{env_name}"

    file_key, source = _load_api_key_from_claude_md(env_names, project_root)
    if file_key:
        return file_key, source

    return "", ""
