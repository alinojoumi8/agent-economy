import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from agents.selection_services import SelectionService
from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay


def config(tmp_path, services):
    value = load_config(Path(__file__).resolve().parents[1] / "runs/jev-domains-offline.yaml")
    value["llm"]["decision_policy"]["services"] = services
    value["outlets"] = [{"id": 1, "name": "The Ledger", "slant": "pro-market"}]
    value.setdefault("information", {})["daily_news_required"] = True
    value.update(engine_semantics_version=20, checkpoint_dir=str(tmp_path / "cp"),
                 report_dir=str(tmp_path / "reports"))
    return value


@pytest.mark.parametrize("semantics", [16, 20])
def test_newsroom_without_live_editor_never_dispatches_or_records_selection(tmp_path, monkeypatch, semantics):
    value = config(tmp_path, ["newsroom"])
    value["engine_semantics_version"] = semantics
    store, world, _ = open_run(value, None, None, data_dir=tmp_path)
    async def forbidden(*args, **kwargs):
        pytest.fail("An outlet without a live editor must not select or write news")
    monkeypatch.setattr(world.gateway, "evaluate", forbidden)
    monkeypatch.setattr(world.gateway, "complete", forbidden)
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE role='editor' AND alive=1") > 0
        store.execute("UPDATE agents SET alive=0 WHERE role='editor'")
        assert asyncio.run(world.newsroom.publish(1)) == []
        assert not store.query("SELECT * FROM events WHERE kind='bounded_selection'")
        assert not store.query("SELECT * FROM llm_calls")
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()


@pytest.mark.parametrize("has_schedule", [False, True])
@pytest.mark.parametrize("recorded", ["absent", "matching", "conflicting"])
def test_replay_typed_oracle_preserves_optional_schedule_contract(monkeypatch, has_schedule, recorded):
    import sqlite3
    from types import SimpleNamespace
    import run
    import reports.acceptance

    question = "Will unemployment exceed 8% within 2 ticks?"
    contract = {"campaign_id": "fixture", "resolution_rule": {"type": "unemployment_above"}}
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.execute("CREATE TABLE predictions(id INTEGER, asked_tick INTEGER, question TEXT)")
    source.execute("CREATE TABLE events(tick INTEGER, kind TEXT, payload_json TEXT)")
    source.execute("INSERT INTO predictions VALUES(1,1,?)", (question,))
    payload = {"prediction_id": 1, "question": question}
    if recorded != "absent":
        payload["governed_contract"] = contract if recorded == "matching" else None
    source.execute("INSERT INTO events VALUES(1,'oracle_typed_request',?)", (json.dumps(payload),))
    checkpoint = {"scheduled_tick": 1, "question": question, "status": "completed", "detail": "fixture"}
    monkeypatch.setattr(run, "_recorded_acceptance_side_effects", lambda *args: (
        {1: checkpoint} if has_schedule else {}, {}, []))
    monkeypatch.setattr(reports.acceptance, "_scheduled_contract", lambda *args: contract)
    monkeypatch.setattr(reports.acceptance, "_record_checkpoint", lambda *args, **kwargs: None)
    observed = []
    async def ask(question, *, governed_contract):
        observed.append(governed_contract)
        return {"prediction_id": 1}
    world = SimpleNamespace(gateway=SimpleNamespace(replay_conn=source), store=SimpleNamespace(tick=1),
        oracle=SimpleNamespace(ask=ask), config={"acceptance": {
            "oracle_latency_source": "scheduled_e2e_v1", "oracle_questions": [{"at_tick": 1, "question": question}]}})
    try:
        if has_schedule and recorded == "conflicting":
            with pytest.raises(RuntimeError, match="disagrees with its schedule"):
                asyncio.run(run.replay_headless(world, 1))
            assert observed == []
        else:
            asyncio.run(run.replay_headless(world, 1))
            assert observed == [contract if has_schedule or recorded == "matching" else None]
    finally:
        source.close()


def test_news_selection_and_attention_preserve_exact_replay(tmp_path, monkeypatch):
    async def forbidden(*a, **k):
        raise AssertionError("network is disabled")
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    store, world, rid = open_run(config(tmp_path, ["newsroom", "attention"]), None, None, data_dir=tmp_path)
    source = Path(store.path)
    try:
        async def steps():
            for _ in range(3):
                await world.step()
        asyncio.run(steps())
        assert not store.query("SELECT * FROM events WHERE kind='decision_error'")
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='bounded_selection'") > 0
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE purpose='reporter'") == 0
        assert store.scalar("SELECT COUNT(*) FROM news_articles") > 0
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store, world, _ = open_run({}, None, rid, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(world, 3))
        proof = verify_replay(source, store.path)
        assert proof["exact"], proof["differences"]
    finally:
        world.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_attention_targets_each_item_and_news_abstention_keeps_daily_brief(tmp_path, monkeypatch):
    seen = []
    original = SelectionService.evaluate
    async def capture(self, service, **kwargs):
        seen.append((service, kwargs))
        if service == "newsroom":
            kwargs["baseline"] = {"story": {"type": "choice", "choice": "none"}}
        return await original(self, service, **kwargs)
    monkeypatch.setattr(SelectionService, "evaluate", capture)
    store, world, _ = open_run(config(tmp_path, ["newsroom", "attention"]), None, None, data_dir=tmp_path)
    try:
        ranked, _receipt = asyncio.run(SelectionService(world.gateway, world.config).rank_attention(
            1, 1, ["A local job opening", "A crop report"], goals="Find work"))
        assert ranked == ["A local job opening", "A crop report"]
        questions = seen[0][1]["questions"]
        assert "A local job opening" in questions["item_0"]["instructions"]
        assert "A crop report" in questions["item_1"]["instructions"]
        asyncio.run(world.step())
        article = store.query_one("SELECT * FROM news_articles WHERE tick=1")
        assert article and "daily brief" in article["headline"]
        assert not store.query("SELECT * FROM llm_calls WHERE purpose IN ('newsroom','reporter')")
    finally:
        world.close()


def test_helper_rest_and_mcp_enforce_identity_scope_and_opt_in(tmp_path):
    from fastapi.testclient import TestClient
    from server.app import create_app
    store, world, _ = open_run(config(tmp_path, ["hermes_helper", "commons"]), None, None, data_dir=tmp_path)
    try:
        service = world.runtime.external
        actor = service.create_connection(tenant_id="fixture", owner_id="owner", display_name="Actor",
            biography="Fixture", preferred_occupation="builder", tier="actor")
        observer = service.create_connection(tenant_id="fixture", owner_id="observer", display_name="Observer",
            biography="Fixture", preferred_occupation="builder", tier="observer")
        asyncio.run(world.step())
        headers = {"Authorization": "Bearer " + actor["credential"]["token"]}
        observer_headers = {"Authorization": "Bearer " + observer["credential"]["token"]}
        with TestClient(create_app(world)) as client:
            turn = client.get("/api/v2/agent/turn", headers=headers).json()
            body = {"target_tick": turn["target_tick"], "observed_projection_hash": turn["projection_hash"],
                    "candidate_actions": [{"type": "do_nothing"}]}
            assert client.post("/api/v2/agent/jev-advice", json=body).status_code == 401
            assert client.post("/api/v2/agent/jev-advice", json=body, headers=observer_headers).status_code == 403
            def tool_names(auth_headers):
                response = client.post("/mcp", headers=auth_headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
                assert response.status_code == 200
                return {item["name"] for item in response.json()["result"]["tools"]}
            assert "ae_jev_recommend" in tool_names(headers)
            assert "ae_jev_recommend" not in tool_names(observer_headers)
            response = client.post("/api/v2/agent/jev-advice", headers=headers, json=body)
            assert response.status_code == 200, response.text
            assert response.json()["submitted"] is False
            assert client.post("/api/v2/agent/jev-advice", headers=headers, json=body).json() == response.json()
            assert not store.query("SELECT * FROM external_action_submissions")
            assert client.post("/api/v2/agent/jev-advice", headers=headers,
                json={**body, "observed_projection_hash": "0" * 64}).status_code == 409
            world.config["llm"]["decision_policy"]["services"] = []
            assert "ae_jev_recommend" not in tool_names(headers)
            assert client.post("/api/v2/agent/jev-advice", headers=headers, json=body).status_code == 409
    finally:
        world.close()


@pytest.mark.parametrize("failure,status,code", [("budget", 402, "helper_budget_exhausted"),
                                                ("provider", 503, "helper_unavailable")])
def test_helper_failures_are_bounded_api_errors_without_provider_details(tmp_path, monkeypatch, failure, status, code):
    from fastapi.testclient import TestClient
    from server.app import create_app
    from llm.gateway import BudgetExceeded, ProviderUnavailable
    from tests.test_external_agent_gateway import _connection
    value = config(tmp_path, ["hermes_helper"])
    value["llm"]["decision_policy"]["primary"] = {"provider": "openrouter_jev", "model": "typesafe/jev-1.13"}
    value["llm"]["providers"] = load_config(Path(__file__).resolve().parents[1] / "runs/jev-live.yaml")["llm"]["providers"]
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key-only")
    # The injected gateway fails before any network dispatch.
    store, world, _ = open_run(value, None, None, data_dir=tmp_path)
    try:
        created = _connection(world)
        service = world.runtime.external
        auth = service.authenticate(created["credential"]["token"])
        turn = service.turn(auth)
        async def fail(*args, **kwargs):
            if failure == "budget":
                raise BudgetExceeded("private accounting details")
            raise ProviderUnavailable("fixture", "fixture", "hermes_selection", "private upstream details")
        monkeypatch.setattr(world.gateway, "evaluate", fail)
        with TestClient(create_app(world)) as client:
            response = client.post("/api/v2/agent/jev-advice", headers={"Authorization": "Bearer " + created["credential"]["token"]},
                json={"target_tick": turn["target_tick"], "observed_projection_hash": turn["projection_hash"],
                      "candidate_actions": [{"type": "do_nothing"}]})
            assert response.status_code == status, response.text
            assert response.json()["detail"]["code"] == code
            assert "private" not in response.text
            assert not store.query("SELECT * FROM external_action_submissions")
    finally:
        world.close()


def test_oracle_selection_is_read_only_and_noul_has_no_confidence(tmp_path):
    from oracle.typed_selection import select_plan, select_probability
    store, world, _ = open_run(config(tmp_path, ["oracle_tools", "oracle_forecast"]), None, None, data_dir=tmp_path)
    try:
        asyncio.run(world.step())
        tick = store.tick
        contract = {"campaign_id": "fixture", "campaign_version": 7, "campaign_key": "prices",
                    "scheduled_tick": tick,
                    "resolution_rule": {"type": "metric_above", "metric": "cpi", "threshold": 100},
                    "deadline_tick": tick + 3}
        before = store.scalar("SELECT COUNT(*) FROM transactions")
        plan = asyncio.run(select_plan(world.oracle, "Will prices rise?", tick, contract))
        evidence = world.oracle.tools.execute_plan(plan["queries"])
        p = asyncio.run(select_probability(world.oracle, "Will prices rise?", tick, contract, evidence))
        assert p == .5
        receipt = json.loads(store.query_one("SELECT payload_json FROM events WHERE kind='bounded_selection' "
            "AND json_extract(payload_json,'$.service')='oracle_forecast'")[0])
        assert set(receipt["answers"]["occurs"]) == {"type", "noul"}
        assert store.scalar("SELECT COUNT(*) FROM transactions") == before
    finally:
        world.close()


def test_hermes_advice_keeps_actor_ownership_and_rejects_stale_or_changed_requests(tmp_path):
    from agents.hermes_selection import recommend
    from agents.external import ExternalAgentError
    from tests.test_external_agent_gateway import _connection
    store, world, _ = open_run(config(tmp_path, ["hermes_helper"]), None, None, data_dir=tmp_path)
    try:
        created = _connection(world)
        service = world.runtime.external
        auth = service.authenticate(created["credential"]["token"])
        turn = service.turn(auth)
        kwargs = {"target_tick": turn["target_tick"], "observed_projection_hash": turn["projection_hash"],
                  "candidate_actions": [{"type": "do_nothing"}], "goal": "Preserve my money"}
        first = asyncio.run(recommend(service, world.gateway, auth, **kwargs))
        assert first["action"] == {"type": "do_nothing"} and first["submitted"] is False
        assert not store.query("SELECT * FROM external_action_submissions")
        second = asyncio.run(recommend(service, world.gateway, auth, **kwargs))
        assert first == second
        with pytest.raises(ExternalAgentError, match="different"):
            asyncio.run(recommend(service, world.gateway, auth, **{**kwargs, "goal": "Changed"}))
        with pytest.raises(ExternalAgentError, match="exact open"):
            asyncio.run(recommend(service, world.gateway, auth, **{**kwargs, "observed_projection_hash": "0" * 64}))
    finally:
        world.close()


def test_commons_duplicate_reactions_do_not_mint_reputation(tmp_path):
    store, world, _ = open_run(config(tmp_path, ["commons"]), None, None, data_dir=tmp_path)
    try:
        asyncio.run(world.step())
        actors = [int(r[0]) for r in store.query("SELECT id FROM agents WHERE alive=1 AND age>=18 ORDER BY id LIMIT 2")]
        post = world.commons.publish(actors[0], body="An observed community update.")
        entry_id = post.get("id") or post.get("entry_id")
        world.commons.react(actors[1], entry_id, "like")
        reputation = store.scalar("SELECT reputation FROM commons_profiles WHERE agent_id=?", (actors[0],))
        count = store.scalar("SELECT COUNT(*) FROM events WHERE kind='commons_reaction_changed'")
        assert world.commons.react(actors[1], entry_id, "like")["idempotent"]
        assert store.scalar("SELECT reputation FROM commons_profiles WHERE agent_id=?", (actors[0],)) == reputation
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='commons_reaction_changed'") == count
        world.commons.react(actors[1], entry_id, "like", active=False)
        assert world.commons.react(actors[1], entry_id, "like", active=False)["idempotent"]
        assert store.scalar("SELECT reputation FROM commons_profiles WHERE agent_id=?", (actors[0],)) == reputation - 1
    finally:
        world.close()


def test_commons_advice_all_operations_are_scoped_and_do_not_create_exposure(tmp_path):
    from agents.commons_selection import observation, recommend, validate_action
    from agents.external import ExternalAgentError, SCOPE_MODERATION
    from server.external_api import _commons_action_schema
    from tests.test_external_agent_gateway import _connection
    store, world, _ = open_run(config(tmp_path, ["commons"]), None, None, data_dir=tmp_path)
    try:
        asyncio.run(world.step())
        created = _connection(world)
        service, commons = world.runtime.external, world.commons
        world._spawn_due_arrivals(store.tick + 1)
        auth = service.authenticate(created["credential"]["token"])
        actor = auth["actor_id"]
        # Exercise the moderator contract as the owner of this one community.
        auth = {**auth, "scopes": list(set(auth["scopes"]) | {SCOPE_MODERATION})}
        other = int(store.scalar("SELECT id FROM agents WHERE alive=1 AND id<>? ORDER BY id LIMIT 1", (actor,)))
        community = commons.create_community(actor, name="Prepared choices")
        post = commons.publish(actor, body="A prepared source.", community_id=community["id"])
        entry = post["id"]
        feed = commons.feed(actor, limit=100)
        impression = next(e["impression_id"] for e in feed["entries"] if e["id"] == entry)
        moderation = commons.moderate(actor, entry, action="label", reason="Check source")
        private = commons.create_community(other, name="Other actor private", visibility="members")
        hidden = commons.publish(other, body="Do not disclose", community_id=private["id"])
        view = observation(service, commons, auth)
        assert "Do not disclose" not in json.dumps(view)
        schema = _commons_action_schema(set(auth["scopes"]))
        actions = [
            {"type": "post", "body": "Already drafted", "community_id": community["id"]},
            {"type": "react", "entry_id": entry, "reaction": "like"},
            {"type": "read", "impression_id": impression},
            {"type": "follow", "agent_id": other},
            {"type": "join_community", "community_id": community["id"]},
            {"type": "create_community", "name": "Prepared new group"},
            {"type": "moderate", "entry_id": entry, "action": "hide", "reason": "A prepared reason"},
            {"type": "appeal", "moderation_action_id": moderation["moderation_action_id"], "body": "Please review"},
        ]
        for action in actions:
            assert validate_action(commons, auth, view, action, schema) == action
        for action in ({"type": "react", "entry_id": hidden["id"], "reaction": "like"},
                       {"type": "read", "impression_id": 999999},
                       {"type": "post", "body": "x", "community_id": private["id"]}):
            with pytest.raises(ValueError):
                validate_action(commons, auth, view, action, schema)
        counts = lambda: tuple(store.scalar("SELECT COUNT(*) FROM " + t) for t in
            ("events", "commons_feed_impressions", "commons_reactions", "commons_appeals", "transactions"))
        before = counts()
        args = dict(observed_tick=store.tick, observation_hash=view["observation_hash"],
                    candidate_actions=actions, action_schema=schema)
        result = asyncio.run(recommend(service, commons, world.gateway, auth, **args))
        assert result["action"] is None and result["submitted"] is False
        assert counts() == before
        assert asyncio.run(recommend(service, commons, world.gateway, auth, **args)) == result
        with pytest.raises(ExternalAgentError, match="stale"):
            asyncio.run(recommend(service, commons, world.gateway, auth,
                **{**args, "observation_hash": "0" * 64}))
    finally:
        world.close()


def test_mocked_jev_services_ballots_and_owned_helper_replay_exactly(tmp_path, monkeypatch):
    from agents.hermes_selection import recommend
    from tests.test_jev_contract import transport
    original_client = httpx.AsyncClient
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key-only")
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        answers = {}
        for key, question in payload["questions"].items():
            kind = question["type"]
            if kind == "choice":
                selected = next((k for k in question["criteria"] if k not in {"escalate", "none", "abstain", "wait"}),
                                next(iter(question["criteria"])))
                answers[key] = {"type": kind, "choice": selected, "confidence": .9}
            elif kind == "score":
                answers[key] = {"type": kind, "score": 2, "confidence": .9}
            else:
                answers[key] = {"type": kind, "noul": .6}
        return httpx.Response(200, json={"model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
            "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 20, "cost": .0000042}})
    transport(monkeypatch, respond)
    value = config(tmp_path, ["newsroom", "attention", "oracle_tools", "oracle_forecast", "hermes_helper"])
    live = load_config(Path(__file__).resolve().parents[1] / "runs/jev-live.yaml")
    value["llm"]["providers"] = live["llm"]["providers"]
    value["llm"]["decision_policy"]["primary"] = live["llm"]["decision_policy"]["primary"]
    value["llm"]["decision_policy"]["strategic_review_interval_ticks"] = 0
    value["budget"].update(cap_usd=1, oracle_reserve_usd=.1, helper_reserve_usd=.1)
    value["recorded_voting"] = {"version": 1}
    value.setdefault("government", {})["election_interval_ticks"] = 1
    store, world, rid = open_run(value, None, None, data_dir=tmp_path)
    source = Path(store.path)
    try:
        service = world.runtime.external
        created = service.create_connection(tenant_id="fixture", owner_id="owner",
            display_name="Owned Hermes citizen", biography="A fixture identity.",
            preferred_occupation="builder", tier="actor")
        # Use the real NIGHT admission boundary; the unit helper force-spawns
        # future arrivals early and is unsuitable for economic replay evidence.
        asyncio.run(world.step())
        auth = service.authenticate(created["credential"]["token"])
        turn = service.turn(auth)
        advice = asyncio.run(recommend(service, world.gateway, auth,
            target_tick=turn["target_tick"], observed_projection_hash=turn["projection_hash"],
            candidate_actions=[{"type": "do_nothing"}]))
        service.submit_action(auth, {"target_tick": turn["target_tick"], "action": advice["action"],
            "observed_projection_hash": turn["projection_hash"], "idempotency_key": "owned-choice"})
        contract = {"campaign_id": "fixture", "campaign_version": 7, "campaign_key": "employment",
            "scheduled_tick": 1, "deadline_tick": 3,
            "resolution_rule": {"type": "unemployment_above", "threshold": .08, "window": 2}}
        answer = asyncio.run(world.oracle.ask("Will unemployment exceed 8% within 2 ticks?", governed_contract=contract))
        assert answer.get("p") == .6, answer
        assert answer["probability_source"] == "typed_noul"
        asyncio.run(world.step())
        assert not store.query("SELECT * FROM events WHERE kind='decision_error'")
        assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='ballot_cast'") > 0
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE purpose='hermes_selection'") == 1
        assert world.gateway.governor._helper_spend_usd == pytest.approx(.0000042)
        assert world.economy.ledger.reconcile()[0]
        assert requests and all(r["model"] == "typesafe/jev-1.13" for r in requests)
    finally:
        world.close()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    async def forbidden(*a, **k):
        raise AssertionError("replay must never dispatch a provider")
    monkeypatch.setattr(original_client, "post", forbidden)
    replay_store, replay_world, _ = open_run({}, None, rid, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 2))
        proof = verify_replay(source, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert replay_world.gateway.replay_execution_stats()["all_nonoperational_calls_consumed_once"]
    finally:
        replay_world.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

@pytest.mark.parametrize('candidate', [{'type': []}, {'type': {}}, {'type': None}, {'type': 1}, {}, []])
def test_hermes_helper_rejects_malformed_type_without_dispatch(tmp_path, monkeypatch, candidate):
    from agents.hermes_selection import recommend
    from agents.external import ExternalAgentError
    from tests.test_external_agent_gateway import _connection
    store, world, _ = open_run(config(tmp_path, ['hermes_helper']), None, None, data_dir=tmp_path)
    try:
        service = world.runtime.external
        auth = service.authenticate(_connection(world)['credential']['token'])
        turn = service.turn(auth)
        before = store.scalar('SELECT COUNT(*) FROM external_security_audit')
        async def denied(*args, **kwargs):
            pytest.fail('malformed candidate dispatched a provider')
        monkeypatch.setattr(world.gateway, 'evaluate', denied)
        with pytest.raises(ExternalAgentError) as exc:
            asyncio.run(recommend(service, world.gateway, auth, target_tick=turn['target_tick'],
                observed_projection_hash=turn['projection_hash'], candidate_actions=[candidate]))
        assert exc.value.code == 'invalid_candidates'
        assert store.scalar('SELECT COUNT(*) FROM external_security_audit') == before
        assert not store.query('SELECT * FROM external_action_submissions')
    finally:
        world.close()
