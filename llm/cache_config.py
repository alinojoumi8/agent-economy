"""Shared normalization for provider prompt-cache configuration."""
from __future__ import annotations

from typing import Any


def normalize_prompt_cache_mode(
        configured_mode: Any, *, legacy_prompt_cache_key: bool = False) -> str:
    """Return the public cache-mode spelling after YAML scalar coercion.

    PyYAML's YAML 1.1 resolver parses an unquoted ``off`` as ``False``.  The
    documented interface accepts that spelling, while a true boolean remains
    invalid and is rejected by readiness validation.
    """
    if configured_mode is None:
        return "openai_key" if legacy_prompt_cache_key else "off"
    if configured_mode is False:
        return "off"
    return str(configured_mode).strip()


__all__ = ["normalize_prompt_cache_mode"]
