"""Optional operational guard around each physical adapter completion.

This interface is deliberately independent of the scientific world store. A
replay consumes recorded inputs and never needs a completion reservation.
"""
from __future__ import annotations

from typing import Any, Protocol

from .adapters import Adapter, AdapterResult


class BudgetExceeded(Exception):
    """A completion cannot proceed within its declared budget."""


class CompletionGuard(Protocol):
    def validate_config(self, config: dict) -> None: ...

    async def complete(
        self, provider: str, adapter: Adapter, model: str,
        messages: list[dict], **kwargs: Any,
    ) -> AdapterResult: ...
