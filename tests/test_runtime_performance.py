"""Bound history work without changing decisions, transcript or admission order."""
from __future__ import annotations

import asyncio
import json

from world.newsroom import Conversations


def _conversations():
    conversations = Conversations.__new__(Conversations)
    conversations.config = {}
    conversations._used_line_keys = set()
    return conversations


def test_fallback_rejects_ungrounded_candidates_before_similarity(monkeypatch):
    conversations = _conversations()
    compared = []

    def compare(text, prior):
        assert not conversations._has_ungrounded_detail(text)
        compared.append(text)
        return False

    monkeypatch.setattr(conversations, "_previously_said", compare)
    result = conversations._unique_fallback_line(
        tick=0, speaker=0, partner_name="Ada", avoid_texts=[])
    assert result == (
        "Ada, the practical concern may be how household budgets respond "
        "before drawing a firm conclusion.")
    assert compared == [result]


def test_used_line_does_not_require_similarity_work(monkeypatch):
    conversations = _conversations()
    conversations._used_line_keys.add("prices may change")

    def expensive(*args):
        raise AssertionError("a known exact duplicate needs no fuzzy comparison")

    monkeypatch.setattr(conversations, "_too_similar", expensive)
    assert conversations._previously_said("PRICES may change!", ["other text"])


def test_similarity_reuses_prior_normalization_without_retaining_worlds(monkeypatch):
    conversations = _conversations()
    original = Conversations._line_key
    normalized = []

    def count(text):
        normalized.append(text)
        return original(text)

    monkeypatch.setattr(Conversations, "_line_key", staticmethod(count))
    prior = [f"Different prior sentence number {index}" for index in range(300)]
    for text in ("Credit could tighten", "Jobs might grow", "Prices may rise"):
        assert not conversations._too_similar(text, prior)
    assert len(normalized) <= len(prior) + 3


def test_similarity_preserves_token_shingle_and_empty_boundaries():
    conversations = _conversations()
    assert not conversations._too_similar("!", ["!"])
    assert conversations._too_similar("PRICE may FALL!", ["price may fall"])
    assert not conversations._too_similar("different", ["price may fall"])
    conversations.config = {"conversations": {
        "similarity_jaccard_threshold": 0.5,
        "similarity_shingle_threshold": 1.0,
    }}
    assert conversations._too_similar("a b c", ["a b d"])
    conversations.config["conversations"]["similarity_jaccard_threshold"] = 0.51
    assert not conversations._too_similar("a b c", ["a b d"])
    assert conversations._too_similar("a b c", ["other a b c ending"])


def test_similarity_cache_is_bounded_and_contains_only_immutable_features():
    Conversations._line_parts.cache_clear()
    for index in range(5000):
        key, tokens, shingles = Conversations._line_parts(f"Prices may change {index}")
        assert isinstance(key, str)
        assert isinstance(tokens, frozenset)
        assert isinstance(shingles, frozenset)
    assert Conversations._line_parts.cache_info().currsize <= 2048
    Conversations._line_parts.cache_clear()


def test_completed_conversations_yield_without_reordering(monkeypatch):
    from types import SimpleNamespace
    conversations = _conversations()
    conversations.e = SimpleNamespace(engine_semantics_version=7)
    completed = []
    observed = []
    pairs = [(index, index + 1) for index in range(20)]

    async def converse(tick, a, b, *, topic_slot):
        completed.append((a, b, topic_slot))

    async def scenario():
        async def observer():
            while True:
                observed.append(len(completed))
                await asyncio.sleep(0)
        task = asyncio.create_task(observer())
        try:
            assert await conversations.evening(1, pairs=pairs) == len(pairs)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    monkeypatch.setattr(conversations, "_converse", converse)
    asyncio.run(scenario())
    assert completed == [(a, b, index) for index, (a, b) in enumerate(pairs)]
    assert len(set(observed)) >= len(pairs) - 1


def _vm_work(store, query, params=()):
    steps = 0

    def progress():
        nonlocal steps
        steps += 100
        return 0

    store.conn.set_progress_handler(progress, 100)
    try:
        rows = [tuple(row) for row in store.query(query, params)]
    finally:
        store.conn.set_progress_handler(None, 0)
    return rows, steps


def test_recent_revenue_work_is_bounded_by_window_not_lifetime(store):
    query = (
        "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) "
        "FROM events WHERE kind='goods_sale' AND tick>? "
        "AND json_extract(payload_json,'$.firm_id')=?")
    with store.savepoint("history"):
        store.executemany("INSERT INTO events(tick,kind,payload_json) VALUES (?,?,?)", [
            (tick, "goods_sale", json.dumps({"firm_id": tick % 2, "total_cents": 100}))
            for tick in range(20000)])
    rows, steps = _vm_work(store, query, (19992, 1))
    assert rows == [(400,)]
    assert steps < 2000, f"seven-day revenue scanned history: {steps} VM steps"


def test_recent_memory_limit_preserves_legacy_ties_and_bounds_work(store):
    query = "SELECT * FROM memories WHERE agent_id=? AND demoted=0 ORDER BY tick DESC LIMIT 200"
    with store.savepoint("memory_history"):
        store.executemany(
            "INSERT INTO memories(agent_id,tick,kind,text,demoted) VALUES (?,?,?,?,?)",
            [(1, index // 20, ("weekly_summary", "observation", "summary")[index % 3],
              f"memory {index}", int(index % 11 == 0)) for index in range(20000)])
    legacy = [tuple(row) for row in store.query(query.replace(
        "FROM memories", "FROM memories INDEXED BY ix_mem_agent_kind_tick"), (1,))]
    actual, steps = _vm_work(store, query, (1,))
    assert actual == legacy
    assert steps < 10000, f"limited memory retrieval scanned history: {steps} VM steps"


def test_existing_belief_lookup_preserves_key_order_and_bounds_work(store):
    with store.savepoint("belief_history"):
        store.executemany("INSERT INTO beliefs(agent_id,key,value,updated_tick) VALUES (?,?,?,?)", [
            (index % 1000, f"fact-{index}", index / 20000, index)
            for index in range(20000)])
    query = "SELECT key,value FROM beliefs WHERE agent_id=?"
    legacy = [tuple(row) for row in store.query(query + " ORDER BY key", (19,))]
    actual, steps = _vm_work(store, query, (19,))
    assert actual == legacy
    assert steps < 2000, f"one-agent belief lookup scanned every agent: {steps} VM steps"


def test_performance_indexes_do_not_change_canonical_data(store):
    from engine.schema import initialize_schema
    from research.hashing import canonical_hashes
    store.log_event(1, "goods_sale", {"firm_id": 1, "total_cents": 123})
    store.insert("memories", agent_id=1, tick=1, kind="observation", text="Prices may rise")
    store.execute("DROP INDEX ix_goods_sales_tick")
    store.execute("DROP INDEX ix_mem_active_recent")
    before = canonical_hashes(store)
    initialize_schema(store.conn)
    initialize_schema(store.conn)
    assert canonical_hashes(store) == before
