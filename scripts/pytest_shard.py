"""Deterministically partition a collected pytest suite for CI.

Load this module as a pytest plugin:

    python -m pytest tests/ -p scripts.pytest_shard \
        --ci-shard-index 0 --ci-shard-count 4
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

import pytest


T = TypeVar("T")


def select_shard(
    items: Sequence[T],
    *,
    shard_index: int,
    shard_count: int,
) -> tuple[list[T], list[T]]:
    """Return the selected and deselected items for one zero-based shard."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(
            f"shard_index must be between 0 and {shard_count - 1}, "
            f"got {shard_index}"
        )

    selected: list[T] = []
    deselected: list[T] = []
    for position, item in enumerate(items):
        target = selected if position % shard_count == shard_index else deselected
        target.append(item)
    return selected, deselected


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ci-shard")
    group.addoption("--ci-shard-index", type=int, default=None)
    group.addoption("--ci-shard-count", type=int, default=None)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    shard_index = config.getoption("--ci-shard-index")
    shard_count = config.getoption("--ci-shard-count")
    if shard_index is None and shard_count is None:
        return
    if shard_index is None or shard_count is None:
        raise pytest.UsageError(
            "--ci-shard-index and --ci-shard-count must be provided together"
        )

    try:
        selected, deselected = select_shard(
            items,
            shard_index=shard_index,
            shard_count=shard_count,
        )
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc

    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
