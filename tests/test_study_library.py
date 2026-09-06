import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from research.artifacts import file_sha256
from research.study_library import StudyLibrary
from research.study_results import StudyIdentityChanged
from server.v2_api import install_v2_routes
from tests.test_study_results import study_snapshot, copied_study  # noqa: F401


@pytest.fixture
def study_api(copied_study, economy, tmp_path):
    result, roots = copied_study
    app = FastAPI()
    config = {**economy.config, "operator_workspace": {"csrf_token": "test-study-csrf"},
              "operator_research": {key: str(value) for key, value in roots.items()}}
    controller = SimpleNamespace(hosted_safe=False)
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=config, economy=economy), controller)
    try:
        with TestClient(app) as client:
            yield client, result, roots, controller, economy
    finally:
        app.state.operator_workspace.close()


HEADERS = {"X-CSRF-Token": "test-study-csrf"}
SCOPE = {"run_id": "test", "tick": "live"}
BASE = "/api/v2/operator/research/studies"


def _selection(client):
    catalog = client.get(BASE, params=SCOPE, headers=HEADERS)
    assert catalog.status_code == 200, catalog.text
    assert catalog.headers["cache-control"] == "private, no-store"
    return catalog.json()["items"][0]


def test_operator_comparison_has_both_domains_and_no_private_paths_or_mutation(study_api):
    client, result, roots, _, economy = study_api
    before_hash, before_mutations = file_sha256(result), economy.store.conn.total_changes
    item = _selection(client)
    response = client.get(f"{BASE}/{item['id']}", headers=HEADERS,
                          params={**SCOPE, "result_sha256": item["result_sha256"]})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    view = response.json()
    assert view["context"] == {"run_id": "test", "fork_id": None, "tick": "live"}
    assert {row["domain"] for row in view["outcomes"]} == {"goods", "equities"}
    assert view["verification"]["status"] == "verified"
    assert view["verification"]["operations"]["provider_calls"] == 0
    for secret in (str(roots["data_root"]), str(result), "source_database", "config_json", "_path"):
        assert secret not in response.text
    assert economy.store.conn.total_changes == before_mutations
    assert file_sha256(result) == before_hash


def test_authority_history_context_and_identity_fail_before_evidence_access(study_api):
    client, _, _, controller, _ = study_api
    assert client.get(BASE, params=SCOPE).status_code == 403
    assert client.get(BASE, params={**SCOPE, "run_id": "other"}, headers=HEADERS).status_code == 409
    assert client.get(BASE, params={**SCOPE, "tick": "1"}, headers=HEADERS).status_code == 409
    assert client.get(BASE, params={**SCOPE, "fork_id": "other"}, headers=HEADERS).status_code == 409
    assert client.get(f"{BASE}/{'f' * 32}", params={**SCOPE, "result_sha256": "0" * 64}, headers=HEADERS).status_code == 404
    controller.hosted_safe = True
    assert client.get(BASE, params=SCOPE, headers=HEADERS).status_code == 403


def test_private_export_revalidates_is_repeatable_and_downloads_only_with_authority(study_api):
    client, _, _, _, economy = study_api
    item = _selection(client)
    view = client.get(f"{BASE}/{item['id']}", params={**SCOPE, "result_sha256": item["result_sha256"]}, headers=HEADERS).json()
    body = {"result_sha256": item["result_sha256"], "verification_sha256": view["verification_sha256"]}
    before = economy.store.conn.total_changes
    path = f"{BASE}/{item['id']}/export"
    assert client.post(path, params=SCOPE, json=body).status_code == 403
    assert client.post(path, params=SCOPE, json={**body, "verification_sha256": "0" * 64}, headers=HEADERS).status_code == 409
    exported = client.post(path, params=SCOPE, json=body, headers=HEADERS)
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "private, no-store"
    receipt = exported.json()
    assert receipt["classification"] == "private_research_evidence"
    repeated = client.post(path, params=SCOPE, json=body, headers=HEADERS)
    assert repeated.json() == receipt
    download = f"/api/v2/operator/research/exports/{receipt['token']}"
    assert client.get(download, params=SCOPE).status_code == 403
    archive = client.get(download, params=SCOPE, headers=HEADERS)
    assert archive.status_code == 200
    assert archive.headers["cache-control"] == "private, no-store"
    assert archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert json.loads(bundle.read("bundle.json"))["classification"] == "private_research_evidence"
    assert economy.store.conn.total_changes == before


def test_changed_report_requires_refresh_and_invalid_evidence_exposes_no_error_contents(study_api):
    client, result, _, _, _ = study_api
    item = _selection(client)
    payload = json.loads(result.read_text())
    payload["summary"]["coverage"]["base"]["eligible"] = 123
    result.write_text(json.dumps(payload))
    response = client.get(f"{BASE}/{item['id']}", params={**SCOPE, "result_sha256": item["result_sha256"]}, headers=HEADERS)
    assert response.status_code == 409
    response = client.get(f"{BASE}/{item['id']}", params={**SCOPE, "result_sha256": file_sha256(result)}, headers=HEADERS)
    assert response.status_code == 422
    result.write_text('{"private": "DO-NOT-EXPOSE-MARKER"}')
    # The previous ID no longer resolves to a valid catalog record.
    response = client.get(f"{BASE}/{item['id']}", params={**SCOPE, "result_sha256": item["result_sha256"]}, headers=HEADERS)
    assert response.status_code == 404
    assert "DO-NOT-EXPOSE-MARKER" not in response.text


def test_library_scan_and_public_catalog_are_bounded(copied_study, tmp_path):
    result, roots = copied_study
    library = StudyLibrary(**roots, export_root=tmp_path / "exports")
    catalog = library.public_catalog()
    assert len(catalog["items"]) == 1 and catalog["items"][0]["verification"] == "not_checked"
    assert "_path" not in json.dumps(catalog)
    library.MAX_CATALOG = 0
    assert library.public_catalog()["truncated"] is True


def test_evidence_change_between_review_and_packaging_cannot_publish_under_old_identity(copied_study, tmp_path, monkeypatch):
    import research.study_library as library_module
    result, roots = copied_study
    library = StudyLibrary(**roots, export_root=tmp_path / "exports")
    item = library.public_catalog()["items"][0]
    view = library.verify(item["id"], item["result_sha256"])
    export = library_module.export_study_bundle

    def changed_export(*args, **kwargs):
        worker = next(roots["data_root"].glob("*/*/worker-*.json"))
        row = json.loads(worker.read_text())
        row["eligibility"] = {"status": "ineligible", "reasons": ["inputs_changed_during_attempt"]}
        worker.write_text(json.dumps(row))
        return export(*args, **kwargs)

    monkeypatch.setattr(library_module, "export_study_bundle", changed_export)
    with pytest.raises(StudyIdentityChanged, match="changed"):
        library.export(item["id"], item["result_sha256"], view["verification_sha256"])
    assert not list((tmp_path / "exports").glob("*.zip"))
