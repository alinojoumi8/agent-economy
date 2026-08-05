from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.external_connector_acceptance import (
    ExternalConnectorReceiptError,
    _public_https_origin,
    validate_external_connector_receipt,
    write_external_connector_receipt,
)
from scripts import run_external_connector_acceptance as connector_runner
from scripts.run_external_connector_acceptance import (
    _request,
    _safe_receipt,
    load_credential_file,
)


COMMIT = "1" * 40
TREE = "2" * 40
HASH = "3" * 64


def receipt(connector: str = "python") -> dict:
    value = {
        "schema": "agent-economy-external-connector-v1",
        "connector": connector,
        "execution_scope": "independent_external",
        "status": "passed",
        "candidate": {"commit": COMMIT, "tree": TREE},
        "client": {"name": f"outside-{connector}", "version": "1.2.3"},
        "signer": {"label": "independent-lab", "independent": True},
        "server_operator": "agent-economy-operator",
        "base_url": "https://agents.example.test",
        "hosted_origin_sha256": "4" * 64,
        "tenant_id": "10000000-0000-4000-8000-000000000001",
        "run_id": "20000000-0000-4000-8000-000000000002",
        "actor_id": "30000000-0000-4000-8000-000000000003",
        "scopes": ["world.act", "world.read"],
        "started_at": "2026-08-05T12:00:00Z",
        "ended_at": "2026-08-05T12:02:00Z",
        "public_exchange": {
            "request_sha256": HASH,
            "response_sha256": "5" * 64,
        },
        "executed_receipts": [{
            "receipt_id": "receipt-1",
            "sha256": "6" * 64,
            "status": "executed",
        }],
        "revocation": {"passed": True, "post_revoke_status": 401},
        "cross_tenant_isolation": {"passed": True, "status": 403},
        "flows": {"authorized_submit": True, "receipt_read": True},
        "notes": "Public hashes only; no transport payloads retained.",
    }
    if connector == "independent_mcp":
        value["discovery"] = {
            "passed": True,
            "authorization_server_sha256": "7" * 64,
            "protected_resource_sha256": "8" * 64,
            "initialize_sha256": "9" * 64,
        }
        del value["flows"]
    if connector in {"hermes", "openclaw"}:
        value["wakes"] = [
            {
                "target_tick": index,
                "submission_id": f"submission-{index}",
                "receipt_id": f"receipt-{index}",
                "status": "executed",
            }
            for index in range(1, 4)
        ]
        value["executed_receipts"] = [
            {
                "receipt_id": f"receipt-{index}",
                "sha256": f"{index + 5:x}" * 64,
                "status": "executed",
            }
            for index in range(1, 4)
        ]
        del value["flows"]
    return value


@pytest.mark.parametrize(
    "connector",
    ["independent_mcp", "hermes", "openclaw", "python", "typescript"],
)
def test_valid_independent_connector_receipts_pass(connector):
    value = receipt(connector)

    validated = validate_external_connector_receipt(
        value,
        expected_candidate={"commit": COMMIT, "tree": TREE},
        expected_connector=connector,
    )

    assert validated == value


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(execution_scope="local"), "independent_external"),
        (lambda value: value["candidate"].update(tree="4" * 40), "candidate"),
        (lambda value: value["signer"].update(label=value["server_operator"]), "signer"),
        (lambda value: value["revocation"].update(passed=False), "revocation"),
        (lambda value: value["cross_tenant_isolation"].update(passed=False), "isolation"),
        (lambda value: value.update(base_url="http://127.0.0.1:8000"), "public HTTPS"),
        (lambda value: value.update(base_url="https://intranet"), "public HTTPS"),
        (lambda value: value.update(base_url="https://[not-an-ipv6-address"), "public HTTPS"),
        (lambda value: value.update(access_token="not-allowed"), "sensitive"),
        (lambda value: value.update(private_payload={"body": "hidden"}), "private"),
    ],
)
def test_validator_rejects_ineligible_or_sensitive_receipts(mutation, message):
    value = receipt()
    mutation(value)

    with pytest.raises(ExternalConnectorReceiptError, match=message):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector="python",
        )


@pytest.mark.parametrize("connector", ["hermes", "openclaw"])
def test_agent_connectors_require_exactly_three_executed_wakes(connector):
    value = receipt(connector)
    value["wakes"].pop()

    with pytest.raises(ExternalConnectorReceiptError, match="three executed wakes"):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector=connector,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda wakes: wakes[0].update(target_tick=True), "tick, submission ID"),
        (lambda wakes: wakes[1].update(submission_id=wakes[0]["submission_id"]), "unique"),
        (lambda wakes: wakes[1].update(receipt_id=wakes[0]["receipt_id"]), "unique"),
    ],
)
def test_agent_connector_wakes_require_strict_ticks_and_unique_ids(mutate, message):
    value = receipt("hermes")
    mutate(value["wakes"])

    with pytest.raises(ExternalConnectorReceiptError, match=message):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector="hermes",
        )


def test_agent_connector_wakes_require_unique_target_ticks():
    value = receipt("hermes")
    value["wakes"][1]["target_tick"] = value["wakes"][0]["target_tick"]

    with pytest.raises(ExternalConnectorReceiptError, match="target ticks"):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector="hermes",
        )


def test_private_embedded_ipv6_origins_are_rejected():
    assert _public_https_origin("https://[::ffff:127.0.0.1]") is False
    assert _public_https_origin("https://[2002:7f00:1::]") is False


def test_mcp_requires_discovery_and_protected_resource_proof():
    value = receipt("independent_mcp")
    del value["discovery"]["protected_resource_sha256"]

    with pytest.raises(ExternalConnectorReceiptError, match="discovery"):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector="independent_mcp",
        )


@pytest.mark.parametrize("connector", ["python", "typescript"])
def test_sdk_connectors_require_submit_and_receipt_read(connector):
    value = receipt(connector)
    value["flows"]["receipt_read"] = False

    with pytest.raises(ExternalConnectorReceiptError, match="authorized submit/read"):
        validate_external_connector_receipt(
            value,
            expected_candidate={"commit": COMMIT, "tree": TREE},
            expected_connector=connector,
        )


def test_writer_is_atomic_idempotent_and_refuses_different_overwrite(tmp_path):
    output = tmp_path / "receipt.json"
    value = receipt()

    first = write_external_connector_receipt(value, output)
    second = write_external_connector_receipt(value, output)

    assert first == second == output
    assert json.loads(output.read_text(encoding="utf-8")) == value
    changed = receipt()
    changed["notes"] = "different public note"
    with pytest.raises(FileExistsError, match="different bytes"):
        write_external_connector_receipt(changed, output)


def test_credential_loader_requires_private_regular_json_file(tmp_path):
    path = tmp_path / "credential.json"
    path.write_text(
        json.dumps({
            "access_token": "process-only-token",
            "isolation_probe_path": "/api/v2/tenants/other/run",
        }),
        encoding="utf-8",
    )
    path.chmod(0o600)

    loaded = load_credential_file(path)

    assert loaded["access_token"] == "process-only-token"
    path.chmod(0o640)
    with pytest.raises(PermissionError, match="mode 600"):
        load_credential_file(path)


def test_credential_loader_rejects_symlink_and_missing_probe(tmp_path):
    target = tmp_path / "credential.json"
    target.write_text(json.dumps({"access_token": "secret"}), encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "credential-link.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="regular file"):
        load_credential_file(link)
    with pytest.raises(ValueError, match="isolation_probe_path"):
        load_credential_file(target)


def test_credential_loader_reads_from_the_validated_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "credential.json"
    path.write_text(json.dumps({
        "access_token": "process-only-token",
        "isolation_probe_path": "/api/v2/tenants/other/run",
    }), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("path reopened after validation")
        ),
    )

    assert load_credential_file(path)["access_token"] == "process-only-token"


def test_connector_urls_resolve_root_paths_against_the_origin():
    assert connector_runner._url(
        "https://agents.example.test/tenant/run?ignored=true",
        "/api/v2/agent/me",
    ) == "https://agents.example.test/api/v2/agent/me"
    assert connector_runner._url(
        "https://agents.example.test/tenant/run",
        "/../oauth/revoke",
    ) == "https://agents.example.test/oauth/revoke"


def test_credential_loader_requires_current_user_ownership(tmp_path, monkeypatch):
    path = tmp_path / "credential.json"
    path.write_text(json.dumps({
        "access_token": "process-only-token",
        "isolation_probe_path": "/api/v2/tenants/other/run",
    }), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(connector_runner.os, "geteuid", lambda: path.stat().st_uid + 1)

    with pytest.raises(PermissionError, match="owned by the current user"):
        load_credential_file(path)


def test_wake_rejects_null_target_tick_with_stable_runtime_error(monkeypatch):
    monkeypatch.setattr(
        connector_runner,
        "_request",
        lambda *_args, **_kwargs: (
            200,
            json.dumps({"target_tick": None, "projection_hash": HASH}).encode("utf-8"),
        ),
    )

    with pytest.raises(RuntimeError, match="lacks target tick or projection hash"):
        connector_runner._execute_wake(
            "https://agents.example.test", "process-only-token",
            after_tick=None, timeout=1.0,
        )


@pytest.mark.parametrize("target_tick", [None, True, "1", 1.0])
def test_safe_receipt_rejects_non_integer_target_ticks(target_tick):
    with pytest.raises(RuntimeError, match="non-integer target tick"):
        _safe_receipt({
            "submission_id": "receipt-1",
            "target_tick": target_tick,
            "status": "executed",
        })


@pytest.mark.parametrize("submission_id", [None, "", "   ", 1])
def test_safe_receipt_requires_a_nonempty_string_submission_id(submission_id):
    with pytest.raises(RuntimeError, match="omitted its submission ID"):
        _safe_receipt({
            "submission_id": submission_id,
            "target_tick": 1,
            "status": "executed",
        })


def test_wake_rejects_receipt_for_a_different_submission(monkeypatch):
    responses = iter([
        (200, json.dumps({"target_tick": 1, "projection_hash": HASH}).encode()),
        (202, json.dumps({"submission_id": "receipt-1", "status": "accepted"}).encode()),
        (200, json.dumps({
            "submission_id": "receipt-other", "target_tick": 1, "status": "executed",
        }).encode()),
    ])
    monkeypatch.setattr(connector_runner, "_request", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="different submission ID"):
        connector_runner._execute_wake(
            "https://agents.example.test", "process-only-token",
            after_tick=None, timeout=1.0,
        )


def test_authenticated_runner_requires_identity_scopes_to_be_a_list(monkeypatch):
    def request(_method, url, **_kwargs):
        if url.endswith("/.well-known/oauth-authorization-server"):
            return 200, b"{}"
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return 200, b"{}"
        if url.endswith("/api/v2/agent/me"):
            return 200, json.dumps({
                "actor": {"id": "agent-1"},
                "scopes": "world.read",
            }).encode("utf-8")
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr(connector_runner, "_request", request)
    args = SimpleNamespace(
        connector="python",
        base_url="https://agents.example.test",
        commit=COMMIT,
        tree=TREE,
        client_name="outside-python",
        client_version="1.2.3",
        timeout=30.0,
        signer_label="independent-lab",
        server_operator="agent-economy-operator",
    )
    credential = {
        "access_token": "process-only-token",
        "isolation_probe_path": "/api/v2/tenants/other/run",
    }

    with pytest.raises(RuntimeError, match="scope list"):
        connector_runner._run_authenticated_acceptance(
            args,
            credential,
            connector_runner._CredentialRevoker(args.base_url, credential),
        )


def test_candidate_ids_use_character_terminology_and_named_hex_helper(tmp_path):
    assert connector_runner.is_lowercase_hex(COMMIT, 40) is True
    args = SimpleNamespace(
        connector="python",
        base_url="https://agents.example.test",
        commit="not-a-commit",
        tree=TREE,
        credential_file=tmp_path / "unused.json",
    )

    with pytest.raises(ValueError, match="40-character hex IDs"):
        connector_runner.run_acceptance(args)


def test_hosted_runner_revokes_credential_when_authenticated_flow_fails(
    tmp_path, monkeypatch,
):
    credential_path = tmp_path / "credential.json"
    credential_path.write_text(json.dumps({
        "access_token": "process-only-token",
        "revocation_token": "process-only-revocation-token",
        "isolation_probe_path": "/api/v2/tenants/other/run",
    }), encoding="utf-8")
    credential_path.chmod(0o600)
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/.well-known/oauth-authorization-server"):
            return 200, b"{}"
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return 200, b"{}"
        if url.endswith("/api/v2/agent/me"):
            return 200, json.dumps({
                "actor": {"id": "agent-1"},
                "tenant_id": "tenant-1",
                "run_id": "run-1",
                "scopes": ["world.read", "world.act"],
            }).encode("utf-8")
        if url.endswith("/api/v2/tenants/other/run"):
            return 403, b"{}"
        if url.endswith("/oauth/revoke"):
            raise RuntimeError("revocation failed")
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(connector_runner, "_request", request)
    monkeypatch.setattr(
        connector_runner,
        "_execute_wake",
        lambda *_args, **_kwargs: (
            {"action_type": "wait"},
            {"submission_id": "receipt-1", "status": "accepted"},
            {"receipt_id": "receipt-1", "target_tick": 1, "status": "executed"},
        ),
    )
    args = SimpleNamespace(
        connector="python",
        base_url="https://agents.example.test",
        commit=COMMIT,
        tree=TREE,
        credential_file=credential_path,
        client_name="outside-python",
        client_version="1.2.3",
        timeout=30.0,
        signer_label="independent-lab",
        server_operator="agent-economy-operator",
    )

    with pytest.raises(RuntimeError, match="revocation failed"):
        connector_runner.run_acceptance(args)

    revocations = [item for item in requests if item[1].endswith("/oauth/revoke")]
    assert len(revocations) == 2
    assert revocations[0][2]["form_body"] == {
        "token": "process-only-revocation-token",
    }


@pytest.mark.parametrize(
    ("isolation_status", "post_revoke_status"),
    [(500, 401), (403, 200)],
)
def test_authenticated_runner_status_fails_when_a_security_gate_fails(
    monkeypatch, isolation_status, post_revoke_status,
):
    identity_reads = 0

    def request(method, url, **_kwargs):
        nonlocal identity_reads
        if url.endswith("/.well-known/oauth-authorization-server"):
            return 200, b"{}"
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return 200, b"{}"
        if url.endswith("/api/v2/agent/me"):
            identity_reads += 1
            if identity_reads == 1:
                return 200, json.dumps({
                    "actor": {"id": "agent-1"},
                    "tenant_id": "tenant-1",
                    "run_id": "run-1",
                    "scopes": ["world.read", "world.act"],
                }).encode("utf-8")
            return post_revoke_status, b"{}"
        if url.endswith("/api/v2/tenants/other/run"):
            return isolation_status, b"{}"
        if url.endswith("/oauth/revoke") and method == "POST":
            return 204, b""
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(connector_runner, "_request", request)
    monkeypatch.setattr(
        connector_runner,
        "_execute_wake",
        lambda *_args, **_kwargs: (
            {"action_type": "wait"},
            {"submission_id": "receipt-1", "status": "accepted"},
            {"receipt_id": "receipt-1", "target_tick": 1, "status": "executed"},
        ),
    )
    args = SimpleNamespace(
        connector="python",
        base_url="https://agents.example.test",
        commit=COMMIT,
        tree=TREE,
        client_name="outside-python",
        client_version="1.2.3",
        timeout=30.0,
        signer_label="independent-lab",
        server_operator="agent-economy-operator",
    )
    credential = {
        "access_token": "process-only-token",
        "isolation_probe_path": "/api/v2/tenants/other/run",
    }

    with pytest.raises(RuntimeError, match="security gates failed") as caught:
        connector_runner._run_authenticated_acceptance(
            args,
            credential,
            connector_runner._CredentialRevoker(args.base_url, credential),
        )

    message = str(caught.value)
    assert f"post_status={post_revoke_status}" in message
    assert f"isolation_status={isolation_status}" in message


def test_hosted_runner_refuses_redirects_without_forwarding_bearer_token():
    received_authorization = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            received_authorization.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"target")

        def log_message(self, _format, *_args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{target.server_port}/elsewhere",
            )
            self.end_headers()
            self.wfile.write(b"redirect refused")

        def log_message(self, _format, *_args):
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
    redirect_thread.start()
    try:
        status, _body = _request(
            "GET", f"http://127.0.0.1:{redirect.server_port}/start",
            token="process-only-secret", timeout=2,
        )

        assert status == 302
        assert received_authorization == []
    finally:
        redirect.shutdown()
        target.shutdown()
        redirect.server_close()
        target.server_close()
        redirect_thread.join(timeout=2)
        target_thread.join(timeout=2)
