"""Review, launch and recover bounded policy studies through the local operator."""
from __future__ import annotations

import json
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from research.artifacts import file_sha256, publish_json
from research.operator_policies import OperatorPolicies
from research.study_jobs import LaunchRequest, PolicyLaunchRequest, PolicyPilotRequest, StudyJobs
from research.study_results import StudyIdentityChanged
from server.v2_api import install_v2_routes
from tests.test_policy_origins import sources_and_spec
from tests.test_policy_studies import base_policy_setup, policy_http_fixture
from tests.test_study_jobs import BASE, CONTEXT, HEADERS, SCOPE


def save_design(root, spec):
    path = root / "comparison.json"
    publish_json(path, {"policies": [{"key": policy.key, "llm": policy.llm,
        "temperature": policy.behavior.temperature, "repair_temperature": policy.repair_temperature}
        for policy in spec.policy_design.policies],
        "tariffs": [tariff.model_dump(mode="json") for tariff in spec.policy_design.tariffs]})
    return path


def request_for(service, **changes):
    choice = service.policy_catalog()["items"][0]
    return {"preset": "POLICY", "design": {"id": choice["id"], "sha256": choice["sha256"]},
        "seeds": [1, 2], "model_replicates": ["draw1", "draw2"], "horizon": 3,
        "max_provider_calls": 500, "max_tokens": 10_000_000, "max_spend_usd": 2.0,
        "max_wall_seconds": 240, "max_disk_mib": 256, **changes}


@pytest.fixture
def policy_jobs(tmp_path):
    config, spec = base_policy_setup()
    service = StudyJobs(tmp_path / "jobs", data_root=tmp_path / "d", out_dir=tmp_path / "r",
        policy_root=tmp_path / "policies")
    path = save_design(service.policies.root, spec)
    return service, path, config, spec


def assert_public(value, *paths):
    text = json.dumps(value)
    for forbidden in ("base_url", "endpoint_reference", "source_database", "resolved_config",
                      '"llm"', '"auth"', "provider-budget.db", "PRIVATE-MARKER"):
        assert forbidden not in text
    for path in paths:
        assert str(path) not in text and str(path).replace("\\", "\\\\") not in text


def test_catalog_and_review_do_not_call_provider_or_construct_world(policy_jobs, monkeypatch):
    jobs, path, _, _ = policy_jobs

    def forbidden(*args, **kwargs):
        pytest.fail("catalog and draft validation must be provider-free")

    monkeypatch.setattr("llm.gateway.Gateway.preflight", forbidden)
    monkeypatch.setattr("world.loop.World.__init__", forbidden)
    before = file_sha256(path)
    caps = jobs.launch_capabilities()
    assert caps["live_models"] is True
    choice = caps["policy_designs"]["items"][0]
    assert choice["tariffs"][0]["input_usd_per_million_tokens"] == .01
    request = PolicyPilotRequest(**request_for(jobs))
    draft = jobs.validate(request, CONTEXT)
    assert draft["executed"] is False
    assert draft["policy_design"]["independent_worlds"] == 2
    assert draft["policy_design"]["assigned_cells"] == draft["estimate"]["worlds"] == 8
    assert draft["estimate"]["source_and_replay_ticks"] == 48
    assert draft["estimate"]["provider_calls_limit"] == 500
    assert draft["provider_allowance"]["verified"] is False
    assert draft["provider_allowance"]["usage"]["provider_calls"] is None
    assert {row["key"] for row in draft["spec"]["analysis"]["outcomes"] if row["purpose"] == "primary"} == {"goods_price", "equity_price"}
    assert draft == jobs.draft(draft["id"], CONTEXT)
    assert_public(caps, jobs.root, path)
    assert_public(draft, jobs.root, path)
    assert file_sha256(path) == before and not jobs.data_root.exists() and not jobs.out_dir.exists()


@pytest.mark.parametrize("change", [
    {"model_replicates": []}, {"model_replicates": ["same", "same"]},
    {"model_replicates": ["a", "b", "c", "d"]}, {"model_replicates": ["../private"]},
    {"seeds": [True]}, {"seeds": [1, 1]}, {"seeds": None},
    {"origin": "verified_checkpoints"}, {"max_provider_calls": 5001}, {"max_tokens": 10_000_001},
    {"max_spend_usd": 5.01}, {"max_spend_usd": float("nan")}, {"max_disk_mib": 1025},
    {"max_wall_seconds": 601}, {"horizon": 31}, {"intervention_tick": 1},
    {"gateway": {"base_url": "http://127.0.0.1"}}, {"pause_after_phase": "MORNING", "pause_after_ticks": 1},
])
def test_policy_request_rejects_unbounded_or_confounding_inputs(policy_jobs, change):
    jobs, _, _, _ = policy_jobs
    with pytest.raises(ValueError):
        PolicyPilotRequest(**{**request_for(jobs), **change})
    assert not jobs.root.exists()


@pytest.mark.parametrize("change", ["malformed", "oversized", "secret", "unknown_field", "duplicate_policy", "bad_tariff"])
def test_unusable_private_design_is_omitted_without_private_errors(policy_jobs, change):
    jobs, path, _, _ = policy_jobs
    value = json.loads(path.read_text())
    if change == "malformed":
        path.write_text("PRIVATE-MARKER")
    elif change == "oversized":
        path.write_bytes(b" " * (OperatorPolicies.MAX_BYTES + 1))
    else:
        if change == "secret":
            value["policies"][1]["llm"]["providers"]["fixture"]["api_key"] = "PRIVATE-MARKER"
        elif change == "unknown_field":
            value["command"] = "PRIVATE-MARKER"
        elif change == "duplicate_policy":
            value["policies"][1]["key"] = value["policies"][0]["key"]
        else:
            value["tariffs"][0]["provider"] = "missing"
        path.write_text(json.dumps(value))
    caps = jobs.launch_capabilities()
    assert caps["live_models"] is False and caps["policy_designs"]["items"] == []
    assert caps["policy_designs"]["unavailable_or_incompatible"] == 1
    assert_public(caps, path)


def test_catalog_enumeration_is_bounded_and_does_not_recurse(policy_jobs, monkeypatch):
    jobs, path, _, spec = policy_jobs
    save_design(path.parent / "nested", spec)
    second = path.with_name("second.json")
    second.write_bytes(path.read_bytes())
    monkeypatch.setattr(OperatorPolicies, "MAX_ITEMS", 1)
    catalog = jobs.policy_catalog()
    assert len(catalog["items"]) == 1 and catalog["truncated"] is True
    assert catalog["unavailable_or_incompatible"] == 0


def test_unavailable_policy_root_preserves_scripted_workflow(policy_jobs):
    from research.study_jobs import PilotRequest
    jobs, path, _, _ = policy_jobs
    jobs.policies = OperatorPolicies(path)  # An owner accidentally selected a file as the directory.
    caps = jobs.launch_capabilities()
    assert caps["live_models"] is False and caps["policy_designs"]["root_unavailable"] is True
    draft = jobs.validate(PilotRequest(preset="G2", seeds=[1, 2], horizon=3, intervention_tick=2), CONTEXT)
    assert draft["executed"] is False and "policy_design" not in draft
    assert_public(caps, path)


def test_launch_requires_reviewed_design_and_explicit_original_allowance(policy_jobs, monkeypatch):
    jobs, path, _, _ = policy_jobs
    starts = []
    monkeypatch.setattr(jobs, "_start", starts.append)
    draft = jobs.validate(PolicyPilotRequest(**request_for(jobs)), CONTEXT)
    body = {"draft_sha256": draft["draft_sha256"], "idempotency_key": "b" * 32}
    for invalid in (False, None, 1, "true"):
        with pytest.raises(ValueError):
            PolicyLaunchRequest(**body, approve_live_inference=invalid)
    with pytest.raises(ValueError, match="explicitly approve"):
        jobs.launch(draft["id"], LaunchRequest(**body), CONTEXT)
    assert not starts and not (jobs.root / "jobs").exists()
    path.write_text(path.read_text() + "\n")
    with pytest.raises(StudyIdentityChanged, match="design changed"):
        jobs.launch(draft["id"], PolicyLaunchRequest(**body, approve_live_inference=True), CONTEXT)
    assert not starts
    second = jobs.validate(PolicyPilotRequest(**request_for(jobs)), CONTEXT)
    launch = PolicyLaunchRequest(draft_sha256=second["draft_sha256"], idempotency_key="c" * 32, approve_live_inference=True)
    state = jobs.launch(second["id"], launch, CONTEXT)
    assert jobs.launch(second["id"], launch, CONTEXT)["id"] == state["id"]
    assert starts == [state["id"]] and state["expected_cells"] == 8
    claim = json.loads((jobs.path("jobs", state["id"]) / "claim.json").read_text())
    assert claim["request"]["approve_live_inference"] is True
    assert claim["policy_root"] == str(jobs.policies.root)


def test_prepared_policy_manifest_preserves_every_pending_draw(policy_jobs):
    from research.studies import prepare_study
    from research.study_jobs import ROOT
    from research.study_library import StudyLibrary
    jobs, _, config, _ = policy_jobs
    spec = jobs._spec(PolicyPilotRequest(**request_for(jobs)), config)
    prepare_study(spec, config, input_root=ROOT, data_root=jobs.data_root, out_dir=jobs.out_dir)
    library = StudyLibrary(data_root=jobs.data_root, out_dir=jobs.out_dir, export_root=jobs.root / "exports")
    item = library.public_catalog()["items"][0]
    view = library.verify(item["id"], item["result_sha256"])
    assert view["state"] == "checkpoint_unavailable" and view["comparison_available"] is False
    assert len({row["cell_key"] for row in view["attempts"]}) == 8
    assert all(row["eligibility"]["status"] == "pending" for row in view["attempts"])
    assert view["provider_allowance"]["verified"] is False and view["export_available"] is False


@pytest.fixture
def policy_api(economy, tmp_path):
    app = FastAPI()
    config = {**economy.config, "operator_workspace": {"csrf_token": "test-study-csrf"},
        "operator_research": {"data_root": str(tmp_path / "d"), "out_dir": str(tmp_path / "r"),
            "policy_root": str(tmp_path / "policies"), "checkpoint_root": str(tmp_path / "parents")}}
    controller = SimpleNamespace(hosted_safe=False)
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=config, economy=economy), controller)
    try:
        with TestClient(app) as client:
            yield client, app.state.study_jobs, app.state.study_library, controller, economy
    finally:
        app.state.operator_workspace.close()


def post(client, path, body):
    response = client.post(BASE + path, params=SCOPE, headers=HEADERS, json=body)
    assert response.status_code in {200, 202}, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def wait_job(client, identity):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"{BASE}/jobs/{identity}", params=SCOPE, headers=HEADERS)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["status"] not in {"starting", "running"}:
            return state
        time.sleep(.2)
    pytest.fail(f"policy supervisor did not finish: {state}")


def test_authorization_precedes_policy_reads_and_dispatch(policy_api, monkeypatch):
    client, jobs, _, controller, _ = policy_api
    save_design(jobs.policies.root, base_policy_setup()[1])
    request = request_for(jobs)
    monkeypatch.setattr(jobs.policies, "catalog", lambda *args: pytest.fail("unauthorized catalog read"))
    monkeypatch.setattr(jobs.policies, "resolve", lambda *args: pytest.fail("unauthorized design read"))
    for path, method in (("/capabilities", "get"), ("/drafts/validate", "post")):
        call = getattr(client, method)
        body = {"json": request} if method == "post" else {}
        assert call(BASE + path, params=SCOPE, **body).status_code == 403
        for change in ({"tick": "1"}, {"run_id": "foreign"}, {"fork_id": "foreign"}):
            assert call(BASE + path, params={**SCOPE, **change}, headers=HEADERS, **body).status_code == 409
        controller.hosted_safe = True
        assert call(BASE + path, params=SCOPE, headers=HEADERS, **body).status_code == 403
        controller.hosted_safe = False
    assert not jobs.data_root.exists()


@pytest.mark.parametrize("origin", ["fresh_genesis", "verified_checkpoints"])
def test_real_policy_job_pause_resume_and_comparison_preserve_original_allowance(policy_api, tmp_path, origin):
    client, jobs, library, _, economy = policy_api
    before = economy.store.conn.total_changes
    with policy_http_fixture(base_policy_setup()) as (config, spec, posts):
        save_design(jobs.policies.root, spec)
        changes = {"pause_after_phase": "MORNING"}
        source_hashes = {}
        if origin == "verified_checkpoints":
            sources, _ = sources_and_spec(config, spec, tmp_path, "preserve_and_resume_phases")
            source_hashes = {path: file_sha256(path) for path in sources}
            choices = jobs.checkpoint_catalog()["items"]
            assert len(choices) == 2
            changes.update(origin=origin, seeds=None, horizon=5,
                checkpoints=[{key: choice[key] for key in ("id", "database_sha256", "receipt_sha256")} for choice in choices])
        request = request_for(jobs, **changes)
        draft = post(client, "/drafts/validate", request)
        assert not posts and not jobs.data_root.exists()
        assert_public(draft, jobs.root, jobs.policies.root)
        body = {"draft_sha256": draft["draft_sha256"], "idempotency_key": "d" * 32}
        assert client.post(f"{BASE}/drafts/{draft['id']}/launch", params=SCOPE, headers=HEADERS, json=body).status_code == 422
        assert not posts
        body["approve_live_inference"] = True
        started = post(client, f"/drafts/{draft['id']}/launch", body)
        assert post(client, f"/drafts/{draft['id']}/launch", body)["id"] == started["id"]
        paused = wait_job(client, started["id"])
        assert paused["status"] == "paused" and paused["resumable"] is True, paused
        assert paused["provider_allowance"]["verified"] is True
        charged = paused["provider_allowance"]["usage"]["provider_calls"]
        assert charged > 0 and len(posts) > 0  # Preflight is charged even when the first cell is scripted.
        pending = library.verify(paused["study_id"], paused["result_sha256"])
        assert pending["contract"] == "operator-policy-working-study-v1"
        assert pending["comparison_available"] is False and len(pending["attempts"]) == 8
        assert len({row["cell_key"] for row in pending["attempts"]}) == 8
        assert pending["provider_allowance"]["usage"]["provider_calls"] == charged
        resume = {"progress_sha256": paused["progress_sha256"], "resume_check_sha256": paused["resume_check_sha256"], "idempotency_key": "e" * 32}
        calls = len(posts)
        stale = {**resume, "progress_sha256": "0" * 64}
        assert client.post(f"{BASE}/jobs/{paused['id']}/resume", params=SCOPE, headers=HEADERS, json=stale).status_code == 409
        assert len(posts) == calls
        child = post(client, f"/jobs/{paused['id']}/resume", resume)
        assert child["parent_job_id"] == paused["id"]
        assert post(client, f"/jobs/{paused['id']}/resume", resume)["id"] == child["id"]
        final = wait_job(client, child["id"])
        assert final["status"] == "completed", final
        assert final["expected_cells"] == final["finished_cells"] == 8
        assert len({row["cell_key"] for row in final["cells"]}) == 8
        response = client.get(f"{BASE}/studies/{final['study_id']}", params={**SCOPE, "result_sha256": final["result_sha256"]}, headers=HEADERS)
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["contract"] == "operator-policy-study-comparison-v1"
        assert view["verification"]["status"] == "verified"
        assert view["provider_allowance"]["usage"]["provider_calls"] > charged
        assert view["provider_allowance"]["limits"] == pending["provider_allowance"]["limits"]
        assert view["provider_allowance"]["usage"]["sealed"] is True
        for domain in ("goods_price", "equity_price"):
            assert view["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 2
        assert all(row == {"assigned": 4, "started": 4, "completed": 4, "eligible": 4} for row in view["cell_coverage"].values())
        assert_public(view, jobs.root, jobs.policies.root)
        calls = len(posts)
        archive = post(client, f"/studies/{final['study_id']}/export", {
            "result_sha256": final["result_sha256"], "verification_sha256": view["verification_sha256"]})
        downloaded = client.get(f"{BASE}/exports/{archive['token']}", params=SCOPE, headers=HEADERS)
        assert downloaded.status_code == 200 and downloaded.headers["cache-control"] == "private, no-store"
        assert downloaded.content[:2] == b"PK" and len(posts) == calls
        if source_hashes:
            assert all(row["inherited_spend_usd"] == 7.5 for row in view["attempts"])
        assert all(file_sha256(path) == expected for path, expected in source_hashes.items())
    assert economy.store.conn.total_changes == before


@pytest.mark.parametrize("failure", ["preflight", "allowance"])
def test_failed_policy_job_retains_charges_and_actual_execution_coverage(policy_api, failure):
    client, jobs, library, _, _ = policy_api
    with policy_http_fixture(base_policy_setup(), smoke_ok=failure != "preflight") as (_, spec, posts):
        save_design(jobs.policies.root, spec)
        draft = post(client, "/drafts/validate", request_for(jobs, max_provider_calls=1 if failure == "allowance" else 500))
        body = {"draft_sha256": draft["draft_sha256"], "idempotency_key": "f" * 32, "approve_live_inference": True}
        started = post(client, f"/drafts/{draft['id']}/launch", body)
        final = wait_job(client, started["id"])
        assert final["status"] == "completed_with_exclusions", final
        view = library.verify(final["study_id"], final["result_sha256"])
        assert view["provider_allowance"]["usage"]["provider_calls"] >= 1 and posts
        assert view["provider_allowance"]["usage"]["sealed"] is True
        if failure == "preflight":
            assert view["provider_allowance"]["preflight_ready"] is False
            for coverage in ("world_coverage", "cell_coverage"):
                assert all(row["started"] == row["completed"] == row["eligible"] == 0 for row in view[coverage].values())
        else:
            # One readiness call succeeds, then the first scripted cell can
            # complete before the live cell exhausts the same allowance.
            assert view["provider_allowance"]["preflight_ready"] is True
            assert view["provider_allowance"]["usage"]["provider_calls"] == 1
            assert view["cell_coverage"]["scripted"]["completed"] == 1
            assert view["cell_coverage"]["model_a"]["completed"] == 0
            assert all(row["eligible"] == 0 for row in view["world_coverage"].values())
        assert not final["resumable"]
