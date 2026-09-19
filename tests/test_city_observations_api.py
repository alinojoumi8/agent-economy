"""Observer bookmark writes remain separate, bounded, scoped and conflict-safe."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from communications.policy import Principal
from operator_workspace import OperatorWorkspace
from server.city_observations_api import CityObservationContext, install_city_observation_routes
from server.projections.envelope import build_envelope


VECTORS = json.loads((Path(__file__).resolve().parents[1] / "dashboard/tests/fixtures/city-observations.json").read_text())


def _fixture(economy, tmp_path, *, hosted=False):
    economy.store.set_meta(tick=6)
    economy.store.commit()
    workspace = OperatorWorkspace(tmp_path / "operator.db", world_path=economy.store.path)
    app = FastAPI()
    install_city_observation_routes(
        app, SimpleNamespace(store=economy.store), SimpleNamespace(hosted_safe=hosted),
        workspace, csrf_token="test-csrf")
    envelope = build_envelope(economy.store, Principal("ordinary-dashboard"), "world.map", {}, as_of_tick=6)
    context = {key: envelope[key] for key in CityObservationContext.model_fields}
    return app, workspace, context


PATH = "/api/v2/operator/city-observations"


def test_bookmarks_persist_in_separate_owner_scoped_store_and_do_not_change_world(economy, tmp_path):
    app, workspace, context = _fixture(economy, tmp_path)
    before = list(economy.store.conn.iterdump())
    with TestClient(app) as client:
        query = {"context": json.dumps(context)}
        initial = client.get(PATH, params=query)
        assert initial.json() == {"context": context, "version": 0, "entries": []}
        assert initial.headers["cache-control"] == "private, no-store"
        body = {"context": context, "expected_version": 0,
                "entries": ["tick=4&event=9&camera=40%2C60%2C4&agent=2&view=diorama", "tick=3&household=7&view=list"]}
        assert client.put(PATH, json=body).status_code == 403
        saved = client.put(PATH, json=body, headers={"X-CSRF-Token": "test-csrf"})
        assert saved.status_code == 200
        assert saved.headers["cache-control"] == "private, no-store"
        assert saved.json()["version"] == 1
        assert client.get(PATH, params=query).json() == saved.json()
        assert client.get(PATH, params=query, headers={"X-Operator-ID": "another-observer"}).json()["entries"] == []
        assert workspace.conn.execute("SELECT COUNT(*) FROM saved_views").fetchone()[0] == 1
        route = workspace.conn.execute("SELECT route FROM saved_views").fetchone()[0]
        workspace.close()
        reopened = OperatorWorkspace(tmp_path / "operator.db", world_path=economy.store.path)
        try:
            assert reopened.get_saved_view(owner_id="local-operator", route=route)["state"]["entries"] == body["entries"]
            audit = reopened.conn.execute("SELECT stable_ref_json FROM operator_audit").fetchone()[0]
            assert json.loads(audit)["kind"] == "city_observations"
            assert "tick=4" not in audit
        finally:
            reopened.close()
    assert list(economy.store.conn.iterdump()) == before


def test_stale_updates_conflict_and_remove_does_not_overwrite_other_saved_views(economy, tmp_path):
    app, workspace, context = _fixture(economy, tmp_path)
    with TestClient(app) as client:
        headers = {"X-CSRF-Token": "test-csrf"}
        body = {"context": context, "expected_version": 0, "entries": ["tick=3&agent=1"]}
        assert client.put(PATH, json=body, headers=headers).status_code == 200
        assert client.put(PATH, json=body, headers=headers).status_code == 409
        assert workspace.conn.execute("SELECT COUNT(*) FROM operator_audit").fetchone()[0] == 1
        assert client.put(PATH, json={**body, "expected_version": 1, "entries": ["tick=4"]}, headers=headers).json()["version"] == 2
        assert client.put(PATH, json={**body, "expected_version": 1}, headers=headers).status_code == 409
        assert client.put(PATH, json=body, headers={**headers, "X-Operator-ID": "other"}).status_code == 200
        assert client.put(PATH, json={**body, "expected_version": 2, "entries": []}, headers=headers).json()["version"] == 3
        assert client.get(PATH, params={"context": json.dumps(context)}, headers={"X-Operator-ID": "other"}).json()["entries"] == body["entries"]
    workspace.close()


@pytest.mark.parametrize("vector", VECTORS)
def test_api_output_matches_the_javascript_navigation_contract(economy, tmp_path, vector):
    app, workspace, context = _fixture(economy, tmp_path)
    with TestClient(app) as client:
        result = client.put(PATH, headers={"X-CSRF-Token": "test-csrf"}, json={
            "context": context, "expected_version": 0, "entries": [vector["input"]]})
        assert result.status_code == 200
        assert result.json()["entries"] == [vector["canonical"]]
    workspace.close()


def test_audit_failure_rolls_back_saved_navigation(economy, tmp_path, monkeypatch):
    app, workspace, context = _fixture(economy, tmp_path)
    def fail_audit(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(workspace, "append_audit", fail_audit)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.put(PATH, headers={"X-CSRF-Token": "test-csrf"}, json={
            "context": context, "expected_version": 0, "entries": ["tick=3"]}).status_code == 500
    assert workspace.conn.execute("SELECT COUNT(*) FROM saved_views").fetchone()[0] == 0
    workspace.close()


@pytest.mark.parametrize("entry", [
    "tick=live", "tick=7", "tick=3&tick=4", "tick=3&fork=foreign", "tick=3&private_body=PRIVATE-CANARY",
    "tick=3&csrf_token=PRIVATE-CANARY", "tick=3&agent=1&firm=2", "tick=3&institution=private:1",
    "tick=3&project=../file", "tick=3&camera=NaN,50,3", "tick=3&camera=50,50,8",
    "tick=3&follow=2&agent=1", "tick=3&agent=9007199254740992", "tick=3&q=" + "a" * 101,
])
def test_invalid_or_private_bookmark_fields_are_rejected_without_writes(economy, tmp_path, entry):
    app, workspace, context = _fixture(economy, tmp_path)
    with TestClient(app) as client:
        result = client.put(PATH, headers={"X-CSRF-Token": "test-csrf"},
                            json={"context": context, "expected_version": 0, "entries": [entry]})
        assert result.status_code == 422
        assert "PRIVATE-CANARY" not in result.text
    assert workspace.conn.execute("SELECT COUNT(*) FROM saved_views").fetchone()[0] == 0
    assert workspace.conn.execute("SELECT COUNT(*) FROM operator_audit").fetchone()[0] == 0
    workspace.close()


def test_context_capacity_duplicate_and_hosted_admission(economy, tmp_path):
    app, workspace, context = _fixture(economy, tmp_path)
    with TestClient(app) as client:
        for field, value in [("run_id", "foreign"), ("fork_id", "child"), ("view_key", "operator-truth"),
                             ("policy_version", 999), ("semantics_version", 999), ("projection_version", 999)]:
            changed = {**context, field: value}
            assert client.get(PATH, params={"context": json.dumps(changed)}).status_code == 409
            assert client.put(PATH, headers={"X-CSRF-Token": "test-csrf"}, json={
                "context": changed, "expected_version": 0, "entries": []}).status_code == 409
        for entries in [["tick=3", "tick=3"], [f"tick=3&agent={n}" for n in range(1, 22)]]:
            assert client.put(PATH, headers={"X-CSRF-Token": "test-csrf"}, json={
                "context": context, "expected_version": 0, "entries": entries}).status_code == 422
    workspace.close()
    app, workspace, context = _fixture(economy, tmp_path, hosted=True)
    with TestClient(app) as client:
        assert client.get(PATH, params={"context": json.dumps(context)}).status_code == 404
        assert client.put(PATH, headers={"X-CSRF-Token": "test-csrf"}, json={
            "context": context, "expected_version": 0, "entries": []}).status_code == 404
    workspace.close()
