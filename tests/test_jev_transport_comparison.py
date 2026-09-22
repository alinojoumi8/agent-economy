"""Comparison is opt-in, bounded, budgeted and stops on the first error."""

import asyncio
import json
import hashlib

import httpx
import pytest

from scripts.compare_jev_transports import compare
from tests.test_jev_contract import evaluation, response, transport


def inputs(tmp_path, count=2):
    paths = []
    for i in range(count):
        path = tmp_path / f"input-{i}.json"
        value = evaluation()
        value["state"]["cash_cents"] += i
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(path)
    return paths


def test_prepare_never_calls_network(tmp_path, monkeypatch):
    def fail(req):
        pytest.fail("Preparation must not dispatch")

    transport(monkeypatch, fail)
    result = asyncio.run(compare(inputs(tmp_path), tmp_path / "prepared"))
    assert result == {"status": "prepared_not_run", "calls": 0}
    assert not list((tmp_path / "prepared").glob("*.db"))


@pytest.mark.parametrize("failure", [False, True])
def test_bounded_comparison_and_stop_without_retry(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("TYPESAFE_API_KEY", "direct-fixture-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-fixture-secret")
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if failure:
            raise httpx.ReadTimeout("fixture", request=req)
        body = response()
        # A real typed answer can exceed the generic chat default of 700.
        body["usage"]["output_tokens"] = 1008
        if req.url.host == "api.typesafe.ai":
            body["model"] = "jev-1.13.0"
            body["usage"].pop("cost")
        return httpx.Response(200, json=body)

    transport(monkeypatch, handler)
    out = tmp_path / "results"
    result = asyncio.run(compare(inputs(tmp_path), out, execute=True))
    assert len(calls) == (1 if failure else 4)
    assert result["attempted"] == len(calls)
    assert result["source_unchanged"]
    assert result["status"] == ("stopped_error" if failure else "complete")
    assert len(list(out.glob("attempt-*.json"))) == len(calls)
    plan = json.loads((out / "plan.json").read_text())
    assert plan["reserved_output_tokens_per_call"] == 2048
    with pytest.raises(FileExistsError):
        asyncio.run(compare(inputs(tmp_path), out, execute=True))


def test_bounds_and_duplicate_inputs(tmp_path):
    paths = inputs(tmp_path, 5)
    for invalid in ([], paths, [paths[0], paths[0]]):
        with pytest.raises(ValueError):
            asyncio.run(compare(invalid, tmp_path / "invalid"))


def test_prepare_hashes_and_preserves_the_exact_validated_bytes(tmp_path):
    path = inputs(tmp_path, 1)[0]
    original = b" \n" + path.read_bytes() + b"\n\t"
    path.write_bytes(original)
    out = tmp_path / "prepared"
    asyncio.run(compare([path], out))
    assert (out / "input-0.json").read_bytes() == original
    plan = json.loads((out / "plan.json").read_text())
    assert (
        plan["input_sha256"][str(path.resolve())]
        == hashlib.sha256(original).hexdigest()
    )


def test_mutation_during_validation_cannot_be_certified_or_dispatched(
    tmp_path, monkeypatch
):
    from scripts import compare_jev_transports as harness

    monkeypatch.setenv("TYPESAFE_API_KEY", "direct-fixture-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-fixture-secret")
    path = inputs(tmp_path, 1)[0]
    original = path.read_bytes()
    validate = harness.validate_evaluation

    def mutate_after_parse(value):
        result = validate(value)
        changed = evaluation()
        changed["state"]["cash_cents"] = 9999
        path.write_text(json.dumps(changed), encoding="utf-8")
        return result

    monkeypatch.setattr(harness, "validate_evaluation", mutate_after_parse)
    calls = []
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(503))
    out = tmp_path / "results"
    with pytest.raises(ValueError, match="Preserved source changed"):
        asyncio.run(compare([path], out, execute=True))
    assert not calls
    assert not list(out.glob("attempt-*.json"))
    assert (out / "input-0.json").read_bytes() == original
    evidence = json.loads((out / "preservation.json").read_text())
    assert not evidence["source_unchanged"]
    assert (
        evidence["before"][str(path.resolve())] == hashlib.sha256(original).hexdigest()
    )
