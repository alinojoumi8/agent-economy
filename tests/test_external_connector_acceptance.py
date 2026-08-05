from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.external_connector_acceptance import (
    ExternalConnectorReceiptError,
    validate_external_connector_receipt,
    write_external_connector_receipt,
)
from scripts.run_external_connector_acceptance import load_credential_file


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
