"""The world shares uvicorn's event loop, so a tick must let it breathe.

These guard the mechanism behind a failure that is invisible from the front
end: while a tick monopolised the loop, HTTP simply stopped being served, and
the dashboard went on animating off its last payload without ever looking
broken. A 300-agent tick blocked the serving loop for 45 s, and the 408 KB map
endpoint never completed at all.

The property under test is not "it is fast" but "the loop gets a turn", which
is why these count loop iterations rather than measuring wall clock.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from agents.runtime import _bounded
from world.loop import World


def _spin(microwork: int = 4000) -> int:
    """Stand in for the per-agent context build: synchronous, never suspends."""
    total = 0
    for index in range(microwork):
        total += index * index
    return total


async def _count_loop_turns(body):
    """Run `body`, counting how many times an independent task got scheduled."""
    turns = 0
    running = True

    async def heartbeat():
        nonlocal turns
        while running:
            turns += 1
            await asyncio.sleep(0)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    result = await body()
    running = False
    beat.cancel()
    try:
        await beat
    except asyncio.CancelledError:
        pass
    return turns, result


def test_bounded_admission_lets_the_serving_loop_run_between_agents():
    """A bounded cohort yields; an unbounded one buries the loop.

    The comparison is the point. asyncio runs every ready callback before it
    polls I/O again, so handing it the whole cohort at once buys everything
    else exactly one turn, no matter how long the cohort takes.
    """
    cohort = 40

    async def one():
        _spin()
        return "done"

    async def scenario():
        async def unbounded():
            return await asyncio.gather(*[one() for _ in range(cohort)])

        async def bounded():
            return await asyncio.gather(*_bounded([one for _ in range(cohort)], 2))

        return await _count_loop_turns(unbounded), await _count_loop_turns(bounded)

    (unbounded_turns, unbounded_result), (bounded_turns, bounded_result) = (
        asyncio.run(scenario()))

    assert len(unbounded_result) == cohort
    assert len(bounded_result) == cohort
    # Roughly a turn per admitted agent, rather than one turn for the whole tick.
    assert bounded_turns >= cohort, (
        f"bounded admission gave the loop only {bounded_turns} turns for {cohort} agents")
    assert bounded_turns > unbounded_turns * 2, (
        f"bounded ({bounded_turns}) must beat unbounded ({unbounded_turns}) decisively; "
        "if this regresses, a tick is starving the HTTP server again")


def test_bounded_preserves_input_order_and_never_exceeds_its_width():
    """Determinism is load-bearing: replay depends on decisions coming back in order."""
    width, cohort = 3, 12
    live = 0
    peak = 0
    admitted: list[int] = []

    def factory(index: int):
        async def run():
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            admitted.append(index)
            await asyncio.sleep(0)
            live -= 1
            return index * 10
        return run

    async def scenario():
        return await asyncio.gather(
            *_bounded([factory(index) for index in range(cohort)], width))

    results = asyncio.run(scenario())

    assert results == [index * 10 for index in range(cohort)]
    assert admitted == sorted(admitted), "agents must be admitted first-in-first-out"
    assert peak <= width, f"peak concurrency {peak} exceeded the configured width {width}"


def test_bounded_width_below_one_is_clamped_not_deadlocked():
    async def one():
        return 1

    async def scenario():
        return await asyncio.gather(*_bounded([one, one], 0))

    assert asyncio.run(scenario()) == [1, 1]


def test_checkpoint_write_is_self_contained_so_it_can_leave_the_loop(store, tmp_path: Path):
    """The copy holds no shared state — that is what makes to_thread safe.

    It ran inline before, and a full copy of a 4.6 GB run database took 27-78 s
    of the serving loop on pause, on stop, and every `checkpoint_every` ticks.

    A real run store rather than a hand-built table, because the snapshot also
    writes a manifest bound to `run_meta` — a toy database passes a test that
    the actual call would fail.
    """
    store.commit()
    dest = tmp_path / "checkpoint.db"

    World._checkpoint_write(store.path, dest)

    assert dest.exists()
    assert Path(f"{dest}.manifest.json").exists(), "the manifest is part of a checkpoint"
    copied = sqlite3.connect(dest)
    try:
        assert copied.execute(
            "SELECT run_id FROM run_meta WHERE id=1").fetchone()[0] == "test"
    finally:
        copied.close()


def test_checkpoint_write_off_the_loop_keeps_the_loop_turning(store, tmp_path: Path):
    """asyncio.to_thread is what the async checkpoint paths rely on."""
    store.commit()
    dest = tmp_path / "checkpoint.db"

    async def scenario():
        async def copy():
            return await asyncio.to_thread(World._checkpoint_write, store.path, dest)
        return await _count_loop_turns(copy)

    turns, _ = asyncio.run(scenario())

    assert dest.exists()
    assert turns > 1, "the loop was blocked for the whole copy"
