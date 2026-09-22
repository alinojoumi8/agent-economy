"""Direct transport safety, identity and metering; all HTTP is mocked."""

import asyncio, json
import httpx, pytest
from llm.typesafe_decisions import TypeSafeDecisionsAdapter, ENDPOINT, validate_endpoint
from llm.adapters import AdapterHTTPError, AdapterTimeoutError
from llm.decisions import response_error
from tests.test_jev_contract import evaluation, transport
from tests.test_typesafe_gateway import response, configuration, request
from llm.gateway import Gateway
from llm.readiness import validate_llm_config, ProviderConfigurationError


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/systemone",
        "http://api.typesafe.ai/v1/systemone",
        "https://api.typesafe.ai/v1/chat/completions",
        ENDPOINT + "?key=x",
        "https://x@api.typesafe.ai/v1/systemone",
    ],
)
def test_endpoint_rejected(url):
    with pytest.raises(ValueError):
        validate_endpoint(url)


def test_direct_wire_no_gateway_fields_and_cost_not_fabricated(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-direct-key")
    calls = []
    body = response()
    body.pop("id")
    body.pop("provider")
    body["usage"].pop("cost")

    def handler(req):
        calls.append(json.loads(req.content))
        assert str(req.url) == ENDPOINT
        assert req.headers["Authorization"] == "Bearer test-direct-key"
        return httpx.Response(200, json=body, headers={"x-request-id": "direct-123"})

    transport(monkeypatch, handler)
    result = asyncio.run(
        TypeSafeDecisionsAdapter({}).complete(
            "jev-1.13.0", [], purpose="decision", context={"_evaluation": evaluation()}
        )
    )
    assert calls == [{"model": "jev-1.13.0", **evaluation()}]
    assert result.reported_usage == (100, 20) and result.reported_cost_usd is None
    assert json.loads(result.text)["id"] == "direct-123"
    assert result.raw["cost_basis"] == "declared_tariff"
    assert (
        response_error(
            json.loads(result.text), evaluation(), expected_models=("jev-1.13.0",)
        )
        is None
    )


@pytest.mark.parametrize("status", [301, 401, 429, 503])
def test_error_does_not_retry_or_expose_secrets(monkeypatch, status):
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-secret")
    calls = []
    transport(
        monkeypatch,
        lambda req: (
            calls.append(req)
            or httpx.Response(
                status,
                text="private-secret",
                headers={"Location": "https://evil.example", "Retry-After": "2"},
            )
        ),
    )
    with pytest.raises(AdapterHTTPError) as e:
        asyncio.run(
            TypeSafeDecisionsAdapter({}).complete(
                "jev-1.13.0",
                [],
                purpose="decision",
                context={"_evaluation": evaluation()},
            )
        )
    assert len(calls) == 1 and "private-secret" not in str(e.value)


def test_timeout_no_retry(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret")
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("secret", request=req)

    transport(monkeypatch, handler)
    with pytest.raises(AdapterTimeoutError) as e:
        asyncio.run(
            TypeSafeDecisionsAdapter({}).complete(
                "jev-1.13.0",
                [],
                purpose="decision",
                context={"_evaluation": evaluation()},
            )
        )
    assert len(calls) == 1 and "secret" not in str(e.value)


@pytest.mark.parametrize(
    "cost,reported",
    [
        (None, False),
        ("0.25", False),
        (-1, False),
        (True, False),
        (1_000_001, False),
        ({}, False),
        (0, True),
        (0.25, True),
    ],
)
def test_cost_basis_matches_actual_metering(monkeypatch, cost, reported):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-secret")
    body = response()
    body["usage"]["cost"] = cost
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = asyncio.run(
        TypeSafeDecisionsAdapter({}).complete(
            "jev-1.13.0", [], purpose="decision", context={"_evaluation": evaluation()}
        )
    )
    assert result.reported_cost_usd == (float(cost) if reported else None)
    assert result.raw["cost_basis"] == (
        "provider_reported" if reported else "declared_tariff"
    )


def test_direct_no_cost_uses_declared_tariff(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "secret")
    body = response()
    body["usage"].pop("cost")
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    cfg = configuration()
    cfg["llm"]["pricing"] = {"jev-1.13.0": {"in": 0.042, "out": 0, "cache": 0.042}}
    gw = Gateway(store, cfg)
    try:
        res = asyncio.run(gw.evaluate(request(), evaluation()))
        assert res.cost_usd == pytest.approx(0.0000042)
    finally:
        gw.close()


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["llm"].update(
            default_route={"provider": "jev", "model": "jev-1.13.0"}
        ),
        lambda c: c["llm"]["decision_policy"]["primary"].update(model="jev-latest"),
        lambda c: c["llm"]["providers"]["jev"].update(api_key_env="OPENROUTER_API_KEY"),
        lambda c: c["llm"]["providers"]["jev"].update(resolved_models=["anything"]),
    ],
)
def test_readiness_rejects_incompatible_routes(change):
    c = configuration()
    change(c)
    with pytest.raises(ProviderConfigurationError):
        validate_llm_config(c, environ={"TEST_JEV_KEY": "x", "OPENROUTER_API_KEY": "y"})
