"""The typed transport must bind answers to supplied options and preserve bills."""
import asyncio
import copy
import json

import httpx
import pytest

from llm.adapters import AdapterHTTPError, build_adapters
from llm.decisions import answer_error, response_error, validate_evaluation
from llm.openrouter_decisions import ENDPOINT, OpenRouterDecisionsAdapter, validate_endpoint


def evaluation():
    return {"state": {"cash_cents": 1500}, "questions": {"action": {
        "type": "choice", "instructions": "Select one supplied option.",
        "criteria": {"buy": {"cost_cents": 500}, "wait": "Keep the cash"}}}}


def response():
    return {"model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
            "id": "fixture-decision", "answers": {"action": {
                "type": "choice", "choice": "buy", "confidence": .8,
                "probabilities": {"buy": .9, "wait": .1}}},
            "usage": {"input_tokens": 100, "output_tokens": 20, "cost": .0000042}}


@pytest.mark.parametrize("change", [
    lambda q: q.update(messages=[]),
    lambda q: q["questions"]["action"].update(type="free_text"),
    lambda q: q["questions"]["action"].update(criteria={"only": "one"}),
    lambda q: q.update(state={"number": float("nan")}),
    lambda q: q.update(state="x" * 32000),
])
def test_reject_invalid_request_before_dispatch(change):
    request = evaluation()
    change(request)
    with pytest.raises((ValueError, TypeError)):
        validate_evaluation(request)


def test_request_is_detached_and_exact():
    original = evaluation()
    detached = validate_evaluation(original)
    detached["state"]["cash_cents"] = 1
    assert original["state"]["cash_cents"] == 1500


@pytest.mark.parametrize("change", [
    lambda a: a.update(choice="invented"),
    lambda a: a.update(confidence=True),
    lambda a: a.update(confidence=float("nan")),
    lambda a: a.update(probabilities={"buy": 1.1, "wait": -.1}),
    lambda a: a.update(probabilities={"buy": .5}),
    lambda a: a.update(probabilities={"buy": .2, "wait": .2}),
    lambda a: a.update(actions=[{"type": "move_deposits"}]),
])
def test_reject_invented_actions_and_invalid_distributions(change):
    result = response()
    change(result["answers"]["action"])
    assert answer_error(result, evaluation())


def test_optional_metadata_is_not_required_or_fabricated():
    result = response()
    result["answers"]["action"] = {"type": "choice", "choice": "wait"}
    for key in ("id", "provider"):
        result.pop(key)
    result["usage"].pop("cost")
    assert response_error(result, evaluation()) is None
    assert "confidence" not in result["answers"]["action"]
    assert response_error(result, evaluation(), expected_models=("a-different-model",))
    result["usage"]["output_tokens"] = True
    assert response_error(result, evaluation())


def test_question_identity_is_exact():
    result = response()
    result["answers"]["other"] = copy.deepcopy(result["answers"]["action"])
    assert answer_error(result, evaluation())


@pytest.mark.parametrize("endpoint", [
    "http://openrouter.ai/api/alpha/decisions",
    "https://openrouter.ai/api/v1/chat/completions",
    "https://elsewhere.example/api/alpha/decisions",
    "https://secret@openrouter.ai/api/alpha/decisions",
    ENDPOINT + "?key=secret",
])
def test_endpoint_does_not_redirect_credentials(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))


def test_openrouter_wire_contract_and_reported_cost(monkeypatch):
    calls = []
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")

    def handler(request):
        calls.append(json.loads(request.content))
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer private-fixture-value"
        return httpx.Response(200, json=response())

    transport(monkeypatch, handler)
    adapter = build_adapters({"providers": {"jev": {
        "kind": "openrouter_decisions", "api_key_env": "TEST_JEV_KEY"}}})["jev"]
    result = asyncio.run(adapter.complete("typesafe/jev-1.13", [], purpose="decision",
                                         context={"_evaluation": evaluation()}))
    assert calls == [{"model": "typesafe/jev-1.13", **evaluation(),
                      "provider": {"allow_fallbacks": False}}]
    assert result.reported_usage == (100, 20)
    assert result.reported_cost_usd == .0000042
    assert result.out_tokens == 20
    assert response_error(json.loads(result.text), evaluation()) is None


@pytest.mark.parametrize("status", [401, 402, 403, 429, 529])
def test_errors_are_redacted_and_transport_does_not_retry(monkeypatch, status):
    calls = []
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-fixture-value", headers={"Retry-After": "2"})

    transport(monkeypatch, handler)
    adapter = OpenRouterDecisionsAdapter({"api_key_env": "TEST_JEV_KEY"})
    with pytest.raises(AdapterHTTPError) as failure:
        asyncio.run(adapter.complete("typesafe/jev-1.13", [], purpose="decision",
                                     context={"_evaluation": evaluation()}))
    assert len(calls) == 1
    assert "private-fixture-value" not in str(failure.value)
    assert failure.value.status_code == status
    assert failure.value.retry_after_s == 2


def test_missing_key_and_prose_purposes_cannot_dispatch(monkeypatch):
    monkeypatch.delenv("TEST_JEV_KEY", raising=False)
    adapter = OpenRouterDecisionsAdapter({"api_key_env": "TEST_JEV_KEY"})
    with pytest.raises(PermissionError):
        asyncio.run(adapter.complete("typesafe/jev-1.13", [], purpose="decision",
                                     context={"_evaluation": evaluation()}))
    with pytest.raises(ValueError):
        asyncio.run(adapter.complete("typesafe/jev-1.13", [], purpose="memory",
                                     context={"_evaluation": evaluation()}))


def test_billable_invalid_answer_retains_metering(monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    result = response()
    result["answers"]["action"]["choice"] = "invented"
    transport(monkeypatch, lambda _: httpx.Response(200, json=result))
    adapter = OpenRouterDecisionsAdapter({"api_key_env": "TEST_JEV_KEY"})
    recorded = asyncio.run(adapter.complete("typesafe/jev-1.13", [], purpose="decision",
                                            context={"_evaluation": evaluation()}))
    assert recorded.reported_usage == (100, 20)
    assert response_error(json.loads(recorded.text), evaluation())
