"""Common events keep draws when unrelated histories consume or insert more."""
from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack

import pytest

from engine.keyed_random import daily_draw, daily_seed, demographic_draw, person_key, policy_seed
from research.artifacts import file_sha256
from run import fork_run, open_run, replay_headless
from tests.test_arrival_personas import _world
from tests.test_research_attempt_integrity import _config
from world.replay_verify import verify_replay


def test_origin_lookup_index_preserves_first_valid_evidence_and_ignores_decoys(store):
    actor = 77
    store.log_event(0, "person_registered", {"random_key": "wrong-subject"}, subject_type="firm", subject_id=actor)
    store.log_event(0, "person_registered", {}, subject_type="agent", subject_id=actor)
    store.log_event(0, "news", {"random_key": "wrong-kind"}, subject_type="agent", subject_id=actor)
    store.log_event(1, "birth", {"random_key": "first-origin"}, subject_type="agent", subject_id=actor)
    store.log_event(2, "person_registered", {"random_key": "later-origin"}, subject_type="agent", subject_id=actor)
    assert person_key(store, actor) == "first-origin"
    assert person_key(store, actor + 1) == f"agent:{actor + 1}"
    query = ("SELECT json_extract(payload_json,'$.random_key') FROM events WHERE subject_type='agent' AND subject_id=? "
             "AND kind IN ('person_registered','birth') AND json_extract(payload_json,'$.random_key') IS NOT NULL ORDER BY id LIMIT 1")
    assert store.scalar(query.replace("FROM events", "FROM events NOT INDEXED"), (actor,)) == person_key(store, actor)
    plan = " ".join(str(row[3]) for row in store.query("EXPLAIN QUERY PLAN " + query, (actor,)))
    assert "ix_events_person_origin_key" in plan and "TEMP B-TREE" not in plan


def test_origin_lookup_index_does_not_keep_an_origin_from_a_rolled_back_insert(store):
    actor = 88
    with pytest.raises(RuntimeError, match="rollback origin"):
        with store.savepoint("temporary_origin"):
            first = store.log_event(1, "birth", {"random_key": "rolled-back"}, subject_type="agent", subject_id=actor)
            assert person_key(store, actor) == "rolled-back"
            raise RuntimeError("rollback origin")
    assert person_key(store, actor) == f"agent:{actor}"
    second = store.log_event(1, "birth", {"random_key": "committed"}, subject_type="agent", subject_id=actor)
    assert second == first
    assert person_key(store, actor) == "committed"


def test_physical_origin_index_can_be_added_to_existing_schema_without_changing_canonical_data(store):
    from engine.schema import initialize_schema
    from research.hashing import canonical_hashes
    store.log_event(1, "birth", {"random_key": "stable-origin"}, subject_type="agent", subject_id=99)
    store.execute("DROP INDEX ix_events_person_origin_key")
    before = canonical_hashes(store)
    initialize_schema(store.conn)
    initialize_schema(store.conn)
    assert canonical_hashes(store) == before
    assert person_key(store, 99) == "stable-origin"
    assert store.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='ix_events_person_origin_key'") == 1


@pytest.fixture
def worlds(tmp_path):
    with ExitStack() as stack:
        def make(name, semantics=16):
            world = _world(tmp_path, name + ".db", semantics=semantics)
            stack.callback(world.close)
            return world
        yield make


def _burn(world):
    for rng in (world.engine_prng, world.lifecycle_prng, world.persona_prng):
        for _ in range(71):
            rng.random()


def test_versioned_draw_vectors_separate_mechanisms_days_and_typed_keys():
    assert daily_seed(42, "health", 8, "agent:3") == 3506924203186260
    assert demographic_draw(42, "illness", 8, 3) == 0.1202908661110349
    cases = [(42, "health", 8, "agent:3"), (43, "health", 8, "agent:3"),
             (42, "birth", 8, "agent:3"), (42, "health", 9, "agent:3"),
             (42, "health", 8, "agent:4"), (42, "health", 8, 3), (42, "health", 8, "3")]
    draws = [daily_draw(*args) for args in cases]
    assert len(set(draws)) == len(cases) and all(0 <= value < 1 for value in draws)
    assert daily_seed(42, "event", 1, {"a": 1, "b": 2}) == daily_seed(42, "event", 1, {"b": 2, "a": 1})


def test_arrival_is_independent_of_other_stream_draws_and_unrelated_schedule_ids(worlds):
    left, right = worlds("left"), worlds("right")
    _burn(right)
    right.store.log_event(0, "unrelated", {}, phase="NIGHT_CLOSE")
    right.economy.lifecycle.schedule_arrival(0, 100)
    schedule = [world.economy.lifecycle.schedule_arrival(0, 1) for world in (left, right)]
    assert schedule[0] != schedule[1]
    snapshots = []
    for world in (left, right):
        before = tuple(rng.getstate() for rng in (world.engine_prng, world.lifecycle_prng, world.persona_prng))
        world._spawn_due_arrivals(1)
        agent = dict(world.store.query_one("SELECT * FROM agents WHERE arrived_tick=1"))
        aid = int(agent["id"])
        account = dict(world.store.query_one("SELECT * FROM accounts WHERE id=?", (agent["checking_account_id"],)))
        ties = [tuple(row) for row in world.store.query("SELECT agent_a,agent_b,weight FROM social_ties WHERE agent_b=? ORDER BY agent_a", (aid,))]
        snapshots.append((agent, account, ties, person_key(world.store, aid)))
        assert before == tuple(rng.getstate() for rng in (world.engine_prng, world.lifecycle_prng, world.persona_prng))
        assert world.economy.ledger.reconcile()[0]
    assert snapshots[0] == snapshots[1]


def test_birth_origin_survives_changed_insert_ids_and_rejects_reassignment(worlds):
    left, right = worlds("birth-left"), worlds("birth-right")
    parent_ids = [int(row["id"]) for row in left.store.query("SELECT id FROM agents WHERE age>=18 ORDER BY id LIMIT 2")]
    parent, other = parent_ids
    right.economy.households.birth(1, other)
    children = [world.economy.households.birth(1, parent) for world in (left, right)]
    assert children[0] != children[1]
    keys = [person_key(world.store, aid) for world, aid in zip((left, right), children)]
    assert keys[0] == keys[1]
    assert left.economy.lifecycle._draw(20, children[0], "illness") == right.economy.lifecycle._draw(20, children[1], "illness")
    assert left.economy.cognition._stable_rank(children[0]) == right.economy.cognition._stable_rank(children[1])
    assert policy_seed(left.economy, "test", 20, children[0], 0) == policy_seed(right.economy, "test", 20, children[1], 0)
    assert person_key(right.store, children[1]) != person_key(right.store, children[1] - 1)
    # Retries return the same child and cannot create a second identity.
    assert right.economy.households.birth(1, parent) == children[1]
    for world in (left, right):
        assert world.economy.ledger.reconcile()[0]


def test_arrival_origin_and_age_basis_survive_an_extra_birth(worlds):
    left, right = worlds("origin-left"), worlds("origin-right")
    parent = int(right.store.scalar("SELECT id FROM agents WHERE age>=18 ORDER BY id LIMIT 1"))
    right.economy.households.birth(1, parent)
    origins = []
    for world in (left, right):
        world.economy.lifecycle.schedule_arrival(0, 2)
        world._spawn_due_arrivals(2)
        row = world.store.query_one("SELECT agent_id,birth_tick FROM person_lifecycle WHERE origin='arrival'")
        aid = int(row["agent_id"])
        origins.append((person_key(world.store, aid), int(row["birth_tick"]), world.economy.cognition._stable_rank(aid)))
        with pytest.raises(ValueError, match="different random identity"):
            world.economy.households.register_person(2, aid, "arrival", random_key="changed")
    assert origins[0] == origins[1]


def test_common_rumor_audience_ignores_unrelated_shock_ids_and_draws(worlds):
    left, right = worlds("rumor-left"), worlds("rumor-right")
    _burn(right)
    right.shocks.schedule("policy_rate", "shock", {"tick": 100}, params={"rate_bps": 500})
    target_keys = []
    shock_keys = []
    for world in (left, right):
        sid = world.shocks.schedule("rumor", "shock", {"tick": 1}, params={"n_agents": 3, "audience": "all_citizens"}, label="common rumor")
        row = world.store.query_one("SELECT * FROM shocks WHERE id=?", (sid,))
        key = world.shocks._random_key(row)
        before = world.engine_prng.getstate()
        world.shocks.evaluate(1)
        assert world.engine_prng.getstate() == before
        assert world.shocks._random_key(world.store.query_one("SELECT * FROM shocks WHERE id=?", (sid,))) == key
        payload = json.loads(world.store.scalar("SELECT payload_json FROM events WHERE kind='rumor' ORDER BY id DESC LIMIT 1"))
        target_keys.append([person_key(world.store, aid) for aid in payload["target_agent_ids"]])
        shock_keys.append(key)
        duplicate = world.shocks.schedule("rumor", "shock", {"tick": 1}, params={"n_agents": 3, "audience": "all_citizens"}, label="common rumor")
        assert world.shocks._random_key(world.store.query_one("SELECT * FROM shocks WHERE id=?", (duplicate,))) != key
    assert target_keys[0] == target_keys[1] and shock_keys[0] == shock_keys[1]


@pytest.mark.parametrize("coverage_first", [False, True])
def test_conversation_selection_ignores_row_order_and_other_draws(worlds, monkeypatch, coverage_first):
    world = worlds("conversations")
    conversations = world.conversations
    conversations.coverage_first = coverage_first
    expected = conversations._sample_pairs(1, 3)
    assert expected
    before = world.engine_prng.getstate()
    assert conversations._sample_pairs(1, 3) == expected
    assert world.engine_prng.getstate() == before
    _burn(world)
    query = world.store.query
    def reordered(sql, *args, **kwargs):
        rows = query(sql, *args, **kwargs)
        return list(reversed(rows)) if "FROM social_ties t" in sql else rows
    monkeypatch.setattr(world.store, "query", reordered)
    assert conversations._sample_pairs(1, 3) == expected
    assert len({aid for pair in expected for aid in pair}) == len(expected) * 2


def test_policy_seed_changes_with_world_seed_and_purpose_but_preserves_legacy(worlds):
    world = worlds("policy")
    aid = int(world.store.scalar("SELECT id FROM agents ORDER BY id LIMIT 1"))
    agent = world.store.query_one("SELECT * FROM agents WHERE id=?", (aid,))
    first = world.runtime.ctx.build(agent, 1)["rng_seed"]
    assert first == world.runtime.ctx.build(agent, 1)["rng_seed"]
    world.economy.config["seed"] += 1
    assert first != world.runtime.ctx.build(agent, 1)["rng_seed"]
    assert policy_seed(world.economy, "policy.reporter", 1, aid, 5) != policy_seed(world.economy, "policy.editor", 1, aid, 5)
    old = worlds("old-policy", semantics=15)
    assert policy_seed(old.economy, "anything", 1, aid, 1234) == 1234
    assert old.economy.lifecycle._draw(8, 3, "illness") == demographic_draw(old.config["seed"], "illness", 8, 3)


def test_arrival_missing_origin_fails_before_spawning_and_birth_rollback_reuses_id_safely(worlds):
    world = worlds("rollback")
    parents = [int(row["id"]) for row in world.store.query("SELECT id FROM agents WHERE age>=18 ORDER BY id LIMIT 2")]
    with pytest.raises(RuntimeError, match="rollback"):
        with world.store.savepoint("injected_failure"):
            removed_id = world.economy.households.birth(1, parents[0])
            removed_key = person_key(world.store, removed_id)
            raise RuntimeError("rollback")
    actual_id = world.economy.households.birth(1, parents[1])
    assert actual_id == removed_id and person_key(world.store, actual_id) != removed_key
    world.store.log_event(0, "arrival_scheduled", {"due_tick": 1}, phase="NIGHT_CLOSE")
    before = [world.store.scalar(f"SELECT COUNT(*) FROM {table}") for table in ("agents", "accounts", "events")]
    with pytest.raises(ValueError, match="lacks its random identity"):
        world._spawn_due_arrivals(1)
    assert before == [world.store.scalar(f"SELECT COUNT(*) FROM {table}") for table in ("agents", "accounts", "events")]
    assert world.economy.ledger.reconcile()[0]


def test_recorded_replay_preserves_rumors_deaths_replacement_arrivals_and_source_bytes(tmp_path):
    config = _config()
    config.update(engine_semantics_version=16, checkpoint_every=0,
                  checkpoint_dir=str(tmp_path / "checkpoints"), report_dir=str(tmp_path / "reports"))
    config["lifecycle"] = {"mortality_baseline_annual_50": 0, "birth_annual_prob": 0,
        "illness_onset_annual_young": 365, "illness_onset_annual_old": 365,
        "sick_to_critical_per_tick": 1, "critical_death_per_tick": 1,
        "medical_cost_cents": 0, "arrival_delay_min": 0, "arrival_delay_max": 0}
    config["shocks"] = [{"kind": "rumor", "tick": 2, "params": {"n_agents": 3}}]
    store, world, source_id = open_run(config, None, None, data_dir=tmp_path)
    source = store.path
    try:
        for _ in range(4):
            asyncio.run(world.step())
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival'") > 0
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='death'") > 0
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='rumor'") == 1
        # Both desk agents have died. Identical rendered reporter requests must
        # retain distinct outlet seeds instead of sharing one durable response.
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE tick=4 AND role='reporter' AND agent_id IS NULL") == 2
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    before = file_sha256(source)
    replay_store, replay, _ = open_run({}, None, source_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay, 4))
        proof = verify_replay(source, replay_store.path)
        assert proof["exact"], proof["differences"]
    finally:
        replay.close()
    assert file_sha256(source) == before


@pytest.mark.parametrize("semantics", [7, 15])
def test_fork_cannot_relabel_historical_origins_as_keyed_streams(tmp_path, monkeypatch, semantics):
    world = _world(tmp_path, "source.db", semantics=semantics)
    source = world.store.path
    world.close()
    before = file_sha256(source)
    monkeypatch.setattr("run.new_run_id", lambda: "unsupported-upgrade")
    with pytest.raises(SystemExit, match="requires fresh genesis"):
        fork_run(source, data_dir=tmp_path, upgrade_semantics=16)
    assert file_sha256(source) == before
    assert not (tmp_path / "unsupported-upgrade.db").exists()
