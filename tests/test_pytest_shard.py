from __future__ import annotations

import pytest

from scripts.pytest_shard import select_shard


def test_select_shard_is_exhaustive_disjoint_and_balanced():
    items = list(range(914))
    selected = [
        select_shard(items, shard_index=index, shard_count=8)[0]
        for index in range(8)
    ]

    assert sorted(item for shard in selected for item in shard) == items
    assert sum(len(shard) for shard in selected) == len(
        set(item for shard in selected for item in shard)
    )
    assert max(map(len, selected)) - min(map(len, selected)) <= 1


@pytest.mark.parametrize(
    ("shard_index", "shard_count"),
    [(-1, 4), (4, 4), (0, 0)],
)
def test_select_shard_rejects_invalid_bounds(shard_index, shard_count):
    with pytest.raises(ValueError):
        select_shard(
            [object()],
            shard_index=shard_index,
            shard_count=shard_count,
        )
