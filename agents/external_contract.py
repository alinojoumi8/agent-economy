"""Shared, dependency-free contracts for external-agent credentials."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib


MAX_OAUTH_CLIENTS = 10_000


@dataclass
class ExternalAgentError(RuntimeError):
    status_code: int
    message: str
    code: str = "external_agent_error"

    def __str__(self) -> str:
        return self.message


def hash_external_credential(value: str) -> str:
    """Return the canonical hash stored by both gateway persistence layers."""

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
