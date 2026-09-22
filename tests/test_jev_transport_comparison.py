"""Comparison is opt-in, bounded, budgeted and stops on the first error."""

import asyncio
import json

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
