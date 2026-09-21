import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay


def configuration(tmp_path):
    config = load_config(Path(__file__).resolve().parents[1] / "runs/jev-domains-offline.yaml")
    config.update(engine_semantics_version=20, recorded_voting={"version": 1},
                  checkpoint_dir=str(tmp_path / "cp"), report_dir=str(tmp_path / "reports"))
    config.setdefault("government", {})["election_interval_ticks"] = 1
    config.setdefault("political_model", {}).update(enabled=True, house_election_interval_ticks=1,
                                                   executive_election_interval_ticks=1)
    return config


@pytest.fixture
def world(tmp_path):
    store, world, _ = open_run(configuration(tmp_path), None, None, data_dir=tmp_path)
    yield world
    world.close()


def test_ballots_admit_only_real_votes_and_close_once(world):
    ballots, store = world.economy.ballots, world.store
    ballots.open_day(1)
    contest = next(c for c in ballots.contests(1) if c["key"] == "fiscal")
    aid = contest["electorate"][0]
    assert not ballots.cast(1, 99999, "fiscal", "expand")["ok"]
    assert not ballots.cast(1, aid, "fiscal", "invented")["ok"]
    assert not ballots.cast(2, aid, "fiscal", "expand")["ok"]
    assert ballots.cast(1, aid, "fiscal", "expand")["ok"]
    assert ballots.cast(1, aid, "fiscal", "expand")["idempotent"]
    assert not ballots.cast(1, aid, "fiscal", "austerity")["ok"]
    ballots.close_day(1)
    count = store.scalar("SELECT COUNT(*) FROM events")
    ballots.close_day(1)
    assert store.scalar("SELECT COUNT(*) FROM events") == count
    closed = next(c for c in ballots._events("ballot_closed", 1) if c["key"] == "fiscal")
    assert closed["counts"] == {"expand": 1}
    assert closed["nonvotes"] == len(contest["electorate"]) - 1
    assert not ballots.cast(1, aid, "fiscal", "expand")["ok"]
    assert world.economy.ledger.reconcile()[0]


def test_missing_and_abstaining_voters_do_not_invent_fiscal_mandate(world):
    b, gov = world.economy.ballots, world.economy.gov
    before = (gov.tax_rate_bps(), gov.benefit_cents())
    b.open_day(1)
    aid = next(c for c in b.contests(1) if c["key"] == "fiscal")["electorate"][0]
    assert b.cast(1, aid, "fiscal", "abstain")["ok"]
    b.close_day(1)
    assert (gov.tax_rate_bps(), gov.benefit_cents()) == before


@pytest.mark.parametrize("selected", [
    {"type": "study_skill", "skill_key": "finance"},
    {"type": "attend_civic_appointment", "appointment_id": 99999},
])
@pytest.mark.parametrize("malformed", [None, 17, "invalid action"])
@pytest.mark.parametrize("recorded_voting", [False, True])
def test_exclusive_actions_reject_malformed_siblings_without_losing_ballots(
        world, selected, malformed, recorded_voting):
    ballots = world.economy.ballots
    ballots.enabled = recorded_voting
    ballots.open_day(1)
    actor = int(world.store.scalar("SELECT id FROM agents WHERE alive=1 AND kind='citizen' AND age>=18 ORDER BY id LIMIT 1"))
    results = world.runtime.executor.execute_actions(1, actor, [
        malformed, selected, {"type": "cast_election_vote", "ballot_key": "fiscal", "choice": "abstain"}])
    assert len(results) == 3
    assert results[0]["ok"] is False and "consumes" in results[0]["reason"]
    assert results[2]["ok"] is recorded_voting
    votes = ballots._events("ballot_cast", 1)
    expected_votes = [(actor, "fiscal", "abstain")] if recorded_voting else []
    assert [(vote["actor_id"], vote["key"], vote["choice"]) for vote in votes] == expected_votes
    assert world.economy.ledger.reconcile()[0]


def _bill(world):
    store, politics = world.store, world.economy.politics
    actor = int(store.scalar("SELECT agent_id FROM legislators WHERE chamber='house' ORDER BY seat_number LIMIT 1"))
    return politics.sponsor_bill(1, actor, {
        "bill_key": "RECORDED-TEST", "title": "Recorded Competition Act", "topic": "competition",
        "summary": "A proposal tested with explicit ballots.", "policy_changes": politics.ai_policy_changes("strict")})["bill_id"]


def test_legislative_ballots_wait_for_all_voters_then_advance_one_stage(world):
    bill_id = _bill(world)
    ballots, store = world.economy.ballots, world.store
    for tick, initial, following in ((1, "committee", "floor_house"), (2, "floor_house", "floor_senate"), (3, "floor_senate", "executive")):
        ballots.open_day(tick)
        contest = next(c for c in ballots.contests(tick) if c.get("bill_id") == bill_id)
        assert contest["electorate"]
        for actor in contest["electorate"]:
            result = ballots.cast(tick, actor, contest["key"], "yes")
            assert result["ok"], result
            assert store.scalar("SELECT status FROM bills WHERE id=?", (bill_id,)) == initial
        ballots.close_day(tick)
        assert store.scalar("SELECT status FROM bills WHERE id=?", (bill_id,)) == following


def test_legislative_no_and_missing_votes_do_not_pass_and_version_changes_expire(world):
    bill_id = _bill(world)
    ballots, store = world.economy.ballots, world.store
    ballots.open_day(1)
    contest = next(c for c in ballots.contests(1) if c.get("bill_id") == bill_id)
    assert ballots.cast(1, contest["electorate"][0], contest["key"], "no")["ok"]
    ballots.close_day(1)
    assert store.scalar("SELECT status FROM bills WHERE id=?", (bill_id,)) == "rejected"
    store.update("bills", bill_id, status="committee")
    ballots.open_day(2)
    second = next(c for c in ballots.contests(2) if c.get("bill_id") == bill_id)
    store.update("bills", bill_id, current_version=2)
    assert not ballots.cast(2, second["electorate"][0], second["key"], "yes")["ok"]
    ballots.close_day(2)
    closed = next(c for c in ballots._events("ballot_closed", 2) if c["key"] == second["key"])
    assert closed["status"] == "superseded"
    assert store.scalar("SELECT status FROM bills WHERE id=?", (bill_id,)) == "committee"


def test_recorded_votes_restart_and_replay_exactly(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("network must remain disabled")
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    store, world, rid = open_run(configuration(tmp_path), None, None, data_dir=tmp_path)
    path = Path(store.path)
    try:
        asyncio.run(world.step(pause_after_phase="MORNING"))
        assert store.get_meta()["next_phase"] == "EXECUTION"
        before = json.loads(store.get_meta()["phase_state_json"])["decisions"]
        assert any(any(a.get("type") == "cast_election_vote" for a in d["envelope"]["actions"]) for d in before)
    finally:
        world.close()
    # Resume the already prepared decisions; no new votes or provider dispatch.
    store, world, _ = open_run({}, rid, None, data_dir=tmp_path)
    try:
        asyncio.run(world.step())
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='ballot_cast'") > 0
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='ballot_closed'") > 0
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store, world, _ = open_run({}, None, rid, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(world, 1))
        proof = verify_replay(path, store.path)
        assert proof["exact"], proof["differences"]
        assert world.gateway._live_dispatch_count == 0
    finally:
        world.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest

@pytest.mark.parametrize('policy_change', ['absent', 'no_politics', 'v3'])
def test_recorded_politics_requires_v4_ballot_surface(tmp_path, policy_change):
    from engine.ballots import RecordedBallots
    from types import SimpleNamespace
    cfg = configuration(tmp_path)
    if policy_change == 'absent':
        cfg['llm'].pop('decision_policy')
    elif policy_change == 'no_politics':
        cfg['llm']['decision_policy']['domains'].remove('politics')
    else:
        cfg['llm']['decision_policy'] = {'version': 'bounded-economic-choice-v3',
            'primary': {'provider': 'scripted', 'model': 'scripted'}}
    with pytest.raises(ValueError, match='requires the V4 politics domain'):
        RecordedBallots(SimpleNamespace(config=cfg, store=None, engine_semantics_version=20))
    cfg['political_model']['enabled'] = False
    assert RecordedBallots(SimpleNamespace(config=cfg, store=None, engine_semantics_version=20)).enabled


@pytest.mark.parametrize('enabled,cadence', [(False,1),(True,3),(True,1)])
def test_ballot_wakes_preserve_governor_cohort_bounds(world, monkeypatch, enabled, cadence):
    runtime = world.runtime
    actors = [dict(r) for r in world.store.query('SELECT * FROM agents WHERE alive=1 AND age>=18 ORDER BY id')]
    tick = 1
    scheduled = actors[:1]
    monkeypatch.setattr(runtime.gw.governor, 'citizens_enabled', lambda: enabled)
    monkeypatch.setattr(runtime.gw.governor, 'cadence_multiplier', lambda: cadence)
    monkeypatch.setattr(runtime.scheduler, 'scheduled_agents', lambda *a, **k: scheduled)
    monkeypatch.setattr(world.economy.ballots, 'pending_actors', lambda t: [a['id'] for a in actors])
    seen = []
    async def decide(t, actor, **kwargs):
        seen.append(actor['id'])
        return {'agent_id': actor['id'], 'actions': []}
    monkeypatch.setattr(runtime, '_decide_pipelined_guarded', decide)
    asyncio.run(runtime.decide_all(tick))
    expected = {scheduled[0]['id']} | ({a['id'] for a in actors if a['id'] % cadence == tick % cadence} if enabled else set())
    assert set(seen) == expected and len(seen) == len(expected)
