"""Resolve API keys from provider config only."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Tuple


def _normalize_secret_value(raw: object) -> str:
    value = str(raw or "").strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        value = value[1:-1].strip()
    return value


def resolve_api_key(
    configured_key: object = "",
    preferred_env_names: Optional[Iterable[str]] = None,
    project_root: Optional[Path] = None,
) -> Tuple[str, str]:
    """Resolve API key only from provider_config.api_key."""
    _ = preferred_env_names
    _ = project_root
    direct_key = _normalize_secret_value(configured_key)
    if direct_key:
        return direct_key, "provider_config.api_key"
    return "", ""
