"""Production acceptance orchestration and evidence receipts.

The evaluator is independent of the live ``World`` object so a reviewer can
regenerate the receipt from persisted run evidence alone.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from engine.ledger import Ledger
from engine.store import Store, load_json
from oracle.rules import ResolutionRuleError, validate_resolution_rule

if TYPE_CHECKING:
    from world.loop import World


REQUIRED_SHOCKS = ("policy_rate", "oil", "rumor", "slant", "scandal")
FAILURE_EVENTS = (
    "provider_failure", "provider_pause", "reconciliation_failure",
    "budget_pause", "report_failed", "oracle_tool_execution_failed",
)
SCHEDULED_E2E_LATENCY_KIND = "scheduled_e2e_v1"
_SCHEDULED_TIMER_DETAIL_KIND = "scheduled_e2e_timer_v1"


def uses_paid_providers(config: dict) -> bool:
    """Return whether any configured route can call a non-local provider."""
    llm = config.get("llm", {})
    routes = [llm.get("default_route", {}), *llm.get("routes", {}).values()]
    providers = {str(route.get("provider", "scripted")) for route in routes}
    return bool(providers.difference({"scripted", "mock", "replay"}))


def resolve_run_db(run_or_path: str | Path, data_dir: str | Path = "data/runs") -> Path:
    candidate = Path(run_or_path)
    if candidate.exists() or candidate.suffix == ".db":
        return candidate
    return Path(data_dir) / f"{candidate}.db"


def _check(check_id: str, label: str, passed: bool, evidence: Any) -> dict:
    return {"id": check_id, "label": label, "passed": bool(passed), "evidence": evidence}


def _p90(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.90 * len(ordered)) - 1)]


def _scheduled_e2e_enabled(config: dict) -> bool:
    return config.get("acceptance", {}).get("oracle_latency_source") == (
        SCHEDULED_E2E_LATENCY_KIND)


def _scheduled_question_key(item: dict) -> str:
    return str(item.get("campaign_key") or f"tick_{int(item['at_tick']):03d}")


def _validate_scheduled_campaign(acceptance: dict, questions: list[dict]) -> None:
    """Fail closed when the governed scheduled-campaign identity is ambiguous."""
    if acceptance.get("oracle_latency_source") != SCHEDULED_E2E_LATENCY_KIND:
        return
    campaign_id = acceptance.get("oracle_campaign_id")
    version = acceptance.get("oracle_campaign_version")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise ValueError("scheduled Oracle campaign requires oracle_campaign_id")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("scheduled Oracle campaign requires a positive integer version")
    keys = [item.get("campaign_key") for item in questions]
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        raise ValueError("every scheduled Oracle question requires campaign_key")
    if len(set(keys)) != len(keys):
        raise ValueError("scheduled Oracle campaign_key values must be unique")
    for item in questions:
        _scheduled_contract(acceptance, item)


def _scheduled_contract(acceptance: dict, item: dict) -> dict:
    """Build the exact engine-owned contract shown to a scheduled Oracle."""
    scheduled_tick = item.get("at_tick")
    horizon = item.get("horizon_ticks")
    if (isinstance(scheduled_tick, bool) or not isinstance(scheduled_tick, int)
            or scheduled_tick < 0):
        raise ValueError("scheduled Oracle at_tick must be a non-negative integer")
    if (isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1):
        raise ValueError("scheduled Oracle horizon_ticks must be a positive integer")
    if "expected_rule" not in item:
        raise ValueError("scheduled Oracle question requires expected_rule")
    try:
        expected_rule = validate_resolution_rule(item["expected_rule"])
    except ResolutionRuleError as exc:
        raise ValueError(f"scheduled Oracle expected_rule is invalid: {exc}") from exc
    return {
        "campaign_id": acceptance["oracle_campaign_id"],
        "campaign_version": acceptance["oracle_campaign_version"],
        "campaign_key": str(item["campaign_key"]),
        "scheduled_tick": scheduled_tick,
        "resolution_rule": expected_rule,
        "deadline_tick": scheduled_tick + horizon,
    }


def _scheduled_request_rows(
    store: Store, *, item: dict, acceptance: dict,
) -> list[tuple[Any, dict, dict]]:
    """Return durable Oracle calls bound to this exact governed contract."""
    tick = int(item["at_tick"])
    question = str(item["question"])
    contract = _scheduled_contract(acceptance, item)
    matched = []
    for row in store.query(
        "SELECT id,purpose,provider,model,cache_key,request_json,latency_ms "
        "FROM llm_calls WHERE tick=? AND role='oracle' "
        "AND purpose IN ('oracle_plan','oracle') ORDER BY id",
        (tick,),
    ):
        request = load_json(row["request_json"], None)
        context = request.get("context") if isinstance(request, dict) else None
        if (isinstance(context, dict)
                and context.get("question") == question
                and context.get("tick") == tick
                and context.get("governed_forecast_contract") == contract):
            matched.append((row, request, context))
    return matched


def _scheduled_call_evidence(
    store: Store, *, item: dict, acceptance: dict,
) -> tuple[list[dict], str | None]:
    """Reconstruct one governed checkpoint's durable logical model calls.

    SQLite IDs are deliberately not part of this evidence.  A resume may reuse
    calls written before the current ``advance_acceptance_run`` invocation, so
    the stable identity is the exact engine-owned forecast contract persisted
    in each request together with its deterministic gateway cache key.
    """
    tick = int(item["at_tick"])
    question = str(item["question"])
    contract = _scheduled_contract(acceptance, item)
    matched = []
    for row, request, context in _scheduled_request_rows(
            store, item=item, acceptance=acceptance):
        system = request.get("system")
        user_text = request.get("user")
        if (not isinstance(system, str) or not system
                or not isinstance(user_text, str) or not user_text):
            return [], "governed Oracle call request envelope is invalid"
        try:
            user = json.loads(user_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [], "governed Oracle call user prompt is not valid JSON"
        cache_key = row["cache_key"]
        if not isinstance(cache_key, str) or not cache_key:
            return [], "governed Oracle call has no deterministic request key"
        provider = row["provider"]
        model = row["model"]
        purpose = str(row["purpose"])
        if (not isinstance(provider, str) or not provider
                or not isinstance(model, str) or not model):
            return [], "governed Oracle call has no provider/model identity"
        expected_key = hashlib.sha1(json.dumps({
            "t": tick,
            "a": None,
            "p": purpose,
            "m": model,
            "msgs": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
        }, sort_keys=True).encode()).hexdigest()
        if cache_key != expected_key:
            return [], "governed Oracle call request key does not match its prompt"
        if any(call["request_key"] == cache_key for call in matched):
            return [], "governed Oracle call set contains duplicate request keys"
        if purpose == "oracle_plan" and user != context:
            return [], "governed Oracle planner prompt differs from its context"
        prior_plans = sum(
            call["purpose"] == "oracle_plan" for call in matched)
        if purpose == "oracle_plan" and prior_plans == 0 and (
                "previous_plan_error" in context or "instruction" in context):
            return [], "initial governed Oracle planner call has retry context"
        if purpose == "oracle_plan" and prior_plans > 0 and (
                not isinstance(context.get("previous_plan_error"), str)
                or not context["previous_plan_error"].strip()
                or not isinstance(context.get("instruction"), str)
                or not context["instruction"].strip()):
            return [], "governed Oracle planner retry lacks sequential retry context"
        if purpose == "oracle":
            common_keys = {
                "governed_forecast_contract", "question",
                "read_only_evidence", "world",
            }
            if (not isinstance(user, dict)
                    or user.get("governed_forecast_contract") != contract
                    or user.get("question") != question
                    or user.get("read_only_evidence") != context.get("evidence")):
                return [], (
                    "governed Oracle answer prompt is not contract/evidence-bound")
            hardened_shape = "tick" in user or "prompt_world" in context
            if hardened_shape:
                if (set(user) != common_keys | {"tick"}
                        or user.get("tick") != tick
                        or "prompt_world" not in context
                        or user.get("world") != context.get("prompt_world")):
                    return [], (
                        "governed Oracle answer prompt has an invalid canonical shape")
                try:
                    canonical_user = json.dumps(
                        user, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError, OverflowError):
                    return [], "governed Oracle answer prompt is not canonical JSON"
                if user_text != canonical_user:
                    return [], "governed Oracle answer prompt is not canonically encoded"
            else:
                # Stored semantics 1-6 and pre-hardening semantics-7 calls used
                # the full digest directly.  Reconstruct it exactly rather than
                # weakening the contract/evidence binding for compatibility.
                legacy_world = {
                    key: value for key, value in context.items()
                    if key not in {
                        "question", "tick", "default_horizon",
                        "governed_forecast_contract", "evidence",
                    }
                }
                if set(user) != common_keys or user.get("world") != legacy_world:
                    return [], (
                        "governed Oracle answer prompt has an invalid legacy shape")
        try:
            call_latency_ms = int(row["latency_ms"] or 0)
        except (TypeError, ValueError, OverflowError):
            return [], "governed Oracle call has invalid latency evidence"
        if call_latency_ms < 0:
            return [], "governed Oracle call has invalid latency evidence"
        matched.append({
            "_id": int(row["id"]),
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "request_key": cache_key,
            "call_latency_ms": call_latency_ms,
        })

    plan_calls = [call for call in matched if call["purpose"] == "oracle_plan"]
    answer_calls = [call for call in matched if call["purpose"] == "oracle"]
    if not 1 <= len(plan_calls) <= 3:
        return [], "governed Oracle checkpoint lacks its unique planner call set"
    if len(answer_calls) != 1:
        return [], "governed Oracle checkpoint lacks exactly one answer call"
    if max(call["_id"] for call in plan_calls) >= answer_calls[0]["_id"]:
        return [], "governed Oracle answer does not follow its planner call set"
    request_keys = [call["request_key"] for call in matched]
    if len(request_keys) != len(set(request_keys)):
        return [], "governed Oracle call set contains duplicate request keys"
    return [
        {key: value for key, value in call.items() if key != "_id"}
        for call in matched
    ], None


def _scheduled_timer_marker(
    store: Store, *, item: dict, acceptance: dict, create: bool = True,
) -> tuple[int, bool]:
    """Persist or recover the wall-clock start of a governed checkpoint."""
    tick = int(item["at_tick"])
    question = str(item["question"])
    campaign_key = _scheduled_question_key(item)
    persisted = store.query_one(
        "SELECT status,detail FROM acceptance_checkpoints "
        "WHERE scheduled_tick=? AND question=?", (tick, question))
    if persisted is not None and str(persisted["status"]) == "pending":
        marker = load_json(persisted["detail"], None)
        start_ns = marker.get("started_epoch_ns") if isinstance(marker, dict) else None
        if (
            isinstance(start_ns, int) and not isinstance(start_ns, bool) and start_ns >= 0
            and marker.get("kind") == _SCHEDULED_TIMER_DETAIL_KIND
            and marker.get("campaign_id") == acceptance.get("oracle_campaign_id")
            and marker.get("campaign_version") == acceptance.get("oracle_campaign_version")
            and marker.get("campaign_key") == campaign_key
            and marker.get("scheduled_tick") == tick
            and marker.get("question") == question
        ):
            return start_ns, True
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {tick} has an invalid persisted timer marker")

    if not create:
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {tick} has no persisted end-to-end timer")

    if store.query_one(
        "SELECT 1 FROM llm_calls WHERE tick=? AND role='oracle' "
        "AND purpose IN ('oracle_plan','oracle') LIMIT 1", (tick,),
    ) is not None:
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {tick} has durable Oracle calls but no "
            "persisted end-to-end timer")

    start_ns = time.time_ns()
    marker = {
        "kind": _SCHEDULED_TIMER_DETAIL_KIND,
        "campaign_id": acceptance.get("oracle_campaign_id"),
        "campaign_version": acceptance.get("oracle_campaign_version"),
        "campaign_key": campaign_key,
        "scheduled_tick": tick,
        "question": question,
        "started_epoch_ns": start_ns,
    }
    _record_checkpoint(
        store, tick, question, "pending",
        detail=json.dumps(marker, sort_keys=True, separators=(",", ":")))
    return start_ns, False


def _resumed_scheduled_latency_ms(started_epoch_ns: int, calls: list[dict]) -> int:
    """Measure resumed E2E time without pretending durable call reuse was free."""
    wall_ms = max(
        0, math.ceil((time.time_ns() - int(started_epoch_ns)) / 1_000_000))
    # Protect the evidence from a backwards wall-clock adjustment.  Persisted
    # provider latency is only a floor: planning/tool/persistence time still
    # belongs to the scheduled end-to-end interval.
    call_floor_ms = sum(int(call.get("call_latency_ms", 0)) for call in calls)
    return max(wall_ms, call_floor_ms)


def _valid_scheduled_prediction(
    store: Store, row, item: dict, *, strict: bool,
) -> tuple[bool, str | None]:
    """Validate the exact forecast admitted for one scheduled checkpoint."""
    if row is None:
        return False, "scheduled prediction is missing"
    evidence = load_json(row["evidence_json"], [])
    if not (
        isinstance(evidence, list)
        and any(isinstance(entry, dict) and entry.get("tool") and "result" in entry
                for entry in evidence)
    ):
        return False, "scheduled prediction has no successful bounded evidence"
    if not strict:
        return True, None
    try:
        probability = float(row["p"])
    except (TypeError, ValueError, OverflowError):
        return False, "scheduled prediction has no finite probability"
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return False, "scheduled prediction probability is outside [0,1]"
    if str(row["status"]) not in {"open", "resolved"}:
        return False, f"scheduled prediction status is {row['status']!r}"
    if str(row["confidence"] or "") not in {"low", "med", "high"}:
        return False, "scheduled prediction confidence is invalid"
    drivers = load_json(row["drivers_json"], [])
    if not (isinstance(drivers, list) and drivers
            and len(drivers) <= 10
            and all(isinstance(driver, str) and driver.strip() and len(driver) <= 300
                    for driver in drivers)):
        return False, "scheduled prediction drivers are invalid"
    rule = load_json(row["resolution_rule_json"], {})
    try:
        rule = validate_resolution_rule(
            rule,
            metric_exists=lambda name: store.query_one(
                "SELECT 1 FROM metrics WHERE name=? LIMIT 1", (name,)) is not None,
        )
    except ResolutionRuleError as exc:
        return False, str(exc)
    expected_rule = item.get("expected_rule")
    if expected_rule is not None:
        try:
            expected_rule = validate_resolution_rule(expected_rule)
        except ResolutionRuleError as exc:
            return False, f"configured expected rule is invalid: {exc}"
        if rule != expected_rule:
            return False, "scheduled prediction does not match its expected rule"
    try:
        asked_tick = int(row["asked_tick"])
        deadline_tick = int(row["deadline_tick"])
    except (TypeError, ValueError, OverflowError):
        return False, "scheduled prediction deadline is invalid"
    if asked_tick != int(item["at_tick"]) or deadline_tick <= asked_tick:
        return False, "scheduled prediction tick/deadline is invalid"
    horizon = item.get("horizon_ticks")
    if horizon is not None and deadline_tick != asked_tick + int(horizon):
        return False, "scheduled prediction deadline does not match its horizon"
    return True, None


def _completion_latency(
    store: Store, *, prediction_id: int, item: dict, acceptance: dict,
) -> tuple[dict | None, str | None]:
    """Return exactly one prediction-bound persisted scheduled latency."""
    bound: list[tuple[int, dict]] = []
    for row in store.query(
        "SELECT id,payload_json FROM events WHERE kind='acceptance_checkpoint_completed' "
        "AND tick=? ORDER BY id", (int(item["at_tick"]),),
    ):
        payload = load_json(row["payload_json"], {})
        if not isinstance(payload, dict):
            continue
        event_prediction_id = payload.get("prediction_id")
        matches_schedule = (
            payload.get("scheduled_tick") == int(item["at_tick"])
            and payload.get("question") == str(item["question"])
            and payload.get("campaign_key") == _scheduled_question_key(item)
        )
        references_prediction = (
            isinstance(event_prediction_id, int)
            and not isinstance(event_prediction_id, bool)
            and event_prediction_id == prediction_id
        )
        if matches_schedule or references_prediction:
            bound.append((int(row["id"]), payload))
    if not bound:
        return None, "prediction has no bound scheduled completion event"
    if len(bound) != 1:
        return None, "prediction has duplicate scheduled completion events"
    event_id, payload = bound[0]
    event_prediction_id = payload.get("prediction_id")
    if (isinstance(event_prediction_id, bool)
            or not isinstance(event_prediction_id, int)
            or event_prediction_id != prediction_id):
        return None, "completion event prediction_id is invalid or dangling"
    if payload.get("scheduled_tick") != int(item["at_tick"]):
        return None, "completion event scheduled_tick is invalid"
    if payload.get("question") != str(item["question"]):
        return None, "completion event question is invalid"
    if payload.get("latency_kind") != SCHEDULED_E2E_LATENCY_KIND:
        return None, "completion event latency_kind is invalid"
    if payload.get("campaign_id") != acceptance.get("oracle_campaign_id"):
        return None, "completion event campaign_id is invalid"
    version = payload.get("campaign_version")
    if (isinstance(version, bool) or not isinstance(version, int)
            or version != acceptance.get("oracle_campaign_version")):
        return None, "completion event campaign_version is invalid"
    if payload.get("campaign_key") != _scheduled_question_key(item):
        return None, "completion event campaign_key is invalid"
    latency = payload.get("latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
        return None, "completion event latency_ms is invalid"
    calls = payload.get("model_calls")
    if not (isinstance(calls, list) and calls
            and all(isinstance(call, dict)
                    and set(call) == {
                        "purpose", "provider", "model", "request_key",
                        "call_latency_ms",
                    }
                    and isinstance(call.get("purpose"), str)
                    and isinstance(call.get("provider"), str)
                    and call.get("provider")
                    and isinstance(call.get("model"), str)
                    and call.get("model")
                    and isinstance(call.get("request_key"), str)
                    and call.get("request_key")
                    and isinstance(call.get("call_latency_ms"), int)
                    and not isinstance(call.get("call_latency_ms"), bool)
                    and call.get("call_latency_ms") >= 0
                    for call in calls)):
        return None, "completion event model-call evidence is invalid"
    purposes = {call["purpose"] for call in calls}
    if not {"oracle_plan", "oracle"}.issubset(purposes):
        return None, "completion event lacks Oracle plan and answer evidence"
    actual_calls, call_error = _scheduled_call_evidence(
        store, item=item, acceptance=acceptance)
    if call_error:
        return None, f"completion event has no valid governed call set: {call_error}"
    if calls != actual_calls:
        return None, "completion event model_calls do not exactly match governed calls"
    call_latency_floor = sum(
        int(call["call_latency_ms"]) for call in actual_calls)
    if latency < call_latency_floor:
        return None, (
            "completion event latency_ms is shorter than its governed call latency sum")
    return {
        "event_id": event_id, "latency_ms": latency,
        "latency_kind": SCHEDULED_E2E_LATENCY_KIND,
        "campaign_id": payload.get("campaign_id"),
        "campaign_version": version,
        "campaign_key": payload.get("campaign_key"),
        "model_calls": actual_calls,
    }, None


def _event_payloads(store: Store, kind: str) -> list[tuple[int, int, dict]]:
    return [
        (int(row["id"]), int(row["tick"]), load_json(row["payload_json"], {}))
        for row in store.query("SELECT id, tick, payload_json FROM events WHERE kind=? ORDER BY id", (kind,))
    ]


def _outflow(store: Store, bank_id: int, start_tick: int, end_tick: int) -> int:
    rows = store.query(
        "SELECT payload_json FROM events WHERE kind='deposit_move' AND tick BETWEEN ? AND ?",
        (start_tick, end_tick),
    )
    return sum(
        int(payload.get("amount_cents", 0))
        for row in rows
        for payload in [load_json(row["payload_json"], {})]
        if int(payload.get("from_bank", -1)) == bank_id
    )


def _rumor_pilot(store: Store) -> tuple[bool, dict]:
    rumors = _event_payloads(store, "rumor")
    if not rumors:
        return False, {"reason": "no rumor event"}
    _, rumor_tick, payload = rumors[0]
    bank_id = int(payload.get("bank_id", 1))
    exposed = [int(value) for value in payload.get("target_agent_ids", [])]
    end_tick = rumor_tick + 9
    participant_conversations: set[int] = set()
    for row in store.query(
        "SELECT c.id, c.participant_ids, m.text FROM conversations c "
        "JOIN messages m ON m.conv_id=c.id WHERE c.tick BETWEEN ? AND ?",
        (rumor_tick, end_tick),
    ):
        participants = {int(value) for value in load_json(row["participant_ids"], [])}
        text = str(row["text"] or "").lower()
        mentions_rumor = "bank" in text and any(
            word in text for word in ("rumor", "hear", "pull", "deposit", "worried", "fail", "under")
        )
        if participants.intersection(exposed) and mentions_rumor:
            participant_conversations.add(int(row["id"]))

    trust_key = f"trust:bank:{bank_id}"
    exposed_set = set(exposed)
    baselines: dict[int, float] = {}
    window_minima: dict[int, float] = {}
    for row in store.query(
        "SELECT id, tick, subject_id, payload_json FROM events "
        "WHERE kind='belief_updated' AND tick<=? ORDER BY tick, id",
        (end_tick,),
    ):
        agent_id = int(row["subject_id"] or 0)
        if agent_id not in exposed_set:
            continue
        update = load_json(row["payload_json"], {})
        if update.get("key") != trust_key:
            continue
        value = update.get("new_value")
        if value is None:
            continue
        value = float(value)
        if int(row["tick"]) < rumor_tick:
            baselines[agent_id] = value
        else:
            window_minima[agent_id] = min(
                value, window_minima.get(agent_id, value))

    missing_history = sorted(exposed_set.difference(baselines))
    history_complete = bool(exposed) and not missing_history
    absolute_drops = {
        agent_id: baselines[agent_id] - min(
            baselines[agent_id], window_minima.get(agent_id, baselines[agent_id]))
        for agent_id in exposed if agent_id in baselines
    }
    relative_drops = {
        agent_id: (drop / baselines[agent_id] if baselines[agent_id] > 0 else 0.0)
        for agent_id, drop in absolute_drops.items()
    }
    dropped_agents = [
        agent_id for agent_id, drop in relative_drops.items()
        if drop + 1e-9 >= 0.20
    ]
    dropped = len(dropped_agents)
    drop_share = dropped / len(exposed) if exposed else 0.0
    pre_outflow = _outflow(store, bank_id, max(0, rumor_tick - 10), rumor_tick - 1)
    post_outflow = _outflow(store, bank_id, rumor_tick, end_tick)
    post_outflow_events = []
    for row in store.query(
        "SELECT id, tick, payload_json FROM events "
        "WHERE kind='deposit_move' AND tick BETWEEN ? AND ? ORDER BY tick, id",
        (rumor_tick, end_tick),
    ):
        move = load_json(row["payload_json"], {})
        if int(move.get("from_bank", -1)) == bank_id:
            post_outflow_events.append({
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "amount_cents": int(move.get("amount_cents", 0)),
            })
    outflow_passed = post_outflow > 2 * pre_outflow if pre_outflow else post_outflow > 0
    evidence = {
        "rumor_tick": rumor_tick, "bank_id": bank_id, "exposed_agents": len(exposed),
        "rumor_conversations_10_ticks": len(participant_conversations),
        "rumor_conversation_ids": sorted(participant_conversations)[:20],
        "trust_drop_agents": dropped, "trust_drop_share": round(drop_share, 4),
        "trust_drop_agent_ids": sorted(dropped_agents)[:20],
        "belief_history_complete": history_complete,
        "missing_belief_history_agent_ids": missing_history[:20],
        "trust_baselines": {
            str(agent_id): round(value, 6)
            for agent_id, value in sorted(baselines.items())[:20]
        },
        "trust_absolute_drops": {
            str(agent_id): round(value, 6)
            for agent_id, value in sorted(absolute_drops.items())[:20]
        },
        "trust_relative_drops": {
            str(agent_id): round(value, 6)
            for agent_id, value in sorted(relative_drops.items())[:20]
        },
        "pre_outflow_cents_10_ticks": pre_outflow,
        "post_outflow_cents_10_ticks": post_outflow,
        "post_outflow_events": post_outflow_events[:20],
    }
    passed = (history_complete and len(participant_conversations) >= 5
              and drop_share >= 0.25 and outflow_passed)
    return passed, evidence


def _shock_effects(store: Store) -> tuple[dict[str, bool], dict[str, Any]]:
    fired_events = {
        str(payload.get("kind")): {
            "event_id": event_id, "tick": tick, "kind": "shock_fired", "payload": payload,
        }
        for event_id, tick, payload in _event_payloads(store, "shock_fired")
    }
    fired = {kind: int(event["tick"]) for kind, event in fired_events.items()}

    def downstream_events(kind: str, shock_kind: str) -> list[dict[str, Any]]:
        return [
            {
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "kind": str(row["kind"]), "payload": load_json(row["payload_json"], {}),
            }
            for row in store.query(
                "SELECT id, tick, kind, payload_json FROM events "
                "WHERE kind=? AND tick>=? ORDER BY tick, id LIMIT 10",
                (kind, fired.get(shock_kind, 10**9)),
            )
        ]

    policy_trace = downstream_events("policy_rate_set", "policy_rate")
    oil_trace = downstream_events("commodity_shock", "oil")
    policy_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='policy_rate_set' AND tick>=?",
        (fired.get("policy_rate", 10**9),), default=0,
    ))
    oil_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='commodity_shock' AND tick>=?",
        (fired.get("oil", 10**9),), default=0,
    ))
    directed_articles: list[dict[str, Any]] = []
    scandal_citing_articles: list[dict[str, Any]] = []
    scandal_ids = {event_id for event_id, _, _ in _event_payloads(store, "firm_scandal")}
    for row in store.query(
        "SELECT id, tick, headline, slant_tags, source_event_ids FROM news_articles ORDER BY tick, id"
    ):
        if (int(row["tick"]) >= fired.get("slant", 10**9)
                and "directed" in load_json(row["slant_tags"], [])):
            directed_articles.append({
                "article_id": int(row["id"]), "tick": int(row["tick"]),
                "headline": str(row["headline"]),
                "slant_tags": load_json(row["slant_tags"], []),
            })
        sources = {int(value) for value in load_json(row["source_event_ids"], [])}
        if scandal_ids.intersection(sources):
            scandal_citing_articles.append({
                "article_id": int(row["id"]), "tick": int(row["tick"]),
                "headline": str(row["headline"]), "source_event_ids": sorted(sources),
            })
    effects = {
        "policy_rate": policy_events > 0,
        "oil": oil_events > 0,
        "slant": bool(directed_articles),
        "scandal": bool(scandal_citing_articles),
    }
    traces = {
        "policy_rate": {
            "source": fired_events.get("policy_rate"), "downstream": policy_trace,
            "passed": effects["policy_rate"],
        },
        "oil": {
            "source": fired_events.get("oil"), "downstream": oil_trace,
            "passed": effects["oil"],
        },
        "rumor": {
            "source": fired_events.get("rumor"), "downstream": None, "passed": False,
        },
        "slant": {
            "source": fired_events.get("slant"), "downstream": directed_articles[:10],
            "passed": effects["slant"],
        },
        "scandal": {
            "source": fired_events.get("scandal"), "downstream": scandal_citing_articles[:10],
            "passed": effects["scandal"],
        },
    }
    evidence = {
        "fired_ticks": fired,
        "policy_rate_events_after_shock": policy_events,
        "commodity_shock_events_after_shock": oil_events,
        "directed_articles": len(directed_articles),
        "scandal_citing_articles": len(scandal_citing_articles),
        "traces": traces,
    }
    return effects, evidence


def _experiment_evidence(path: str | Path | None) -> tuple[bool, dict]:
    if not path:
        return False, {"reason": "no experiment JSON supplied"}
    evidence_path = Path(path)
    if not evidence_path.exists():
        return False, {"reason": f"experiment JSON not found: {evidence_path}"}
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    seeds = {int(seed) for seed in payload.get("spec", {}).get("seeds", [])}
    results = payload.get("results", [])
    arms = {str(result.get("arm")) for result in results}
    all_reconciled = bool(payload.get("summary", {}).get("all_reconciled"))
    complete = all(
        any(int(result.get("seed", -1)) == seed and result.get("arm") == arm for result in results)
        for seed in seeds for arm in ("treatment", "control")
    )
    evidence = {
        "path": str(evidence_path), "seeds": sorted(seeds), "arms": sorted(arms),
        "runs": len(results), "all_reconciled": all_reconciled,
    }
    passed = len(seeds) >= 5 and arms >= {"treatment", "control"} and complete and all_reconciled
    return passed, evidence


def _phenomena_evidence(store: Store, path: str | Path | None) -> tuple[bool, dict]:
    if not path:
        return False, {"reason": "no phenomena evidence supplied"}
    evidence_path = Path(path)
    if not evidence_path.exists():
        return False, {"reason": f"phenomena evidence not found: {evidence_path}"}
    payload = yaml.safe_load(evidence_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return False, {"reason": "phenomena evidence must be a YAML mapping"}
    expected_run_id = str(store.get_meta()["run_id"])
    evidence_run_id = str(payload.get("run_id", "")).strip()
    if evidence_run_id != expected_run_id:
        return False, {
            "reason": "phenomena evidence is not bound to this run",
            "expected_run_id": expected_run_id,
            "evidence_run_id": evidence_run_id or None,
            "path": str(evidence_path),
        }
    verified = []
    for item in payload.get("phenomena", []):
        metric = str(item.get("metric", ""))
        start_tick = int(item.get("start_tick", -1))
        end_tick = int(item.get("end_tick", -1))
        direction = item.get("direction")
        start = store.scalar(
            "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (metric, start_tick), default=None,
        )
        end = store.scalar(
            "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (metric, end_tick), default=None,
        )
        delta = None if start is None or end is None else float(end) - float(start)
        direction_ok = delta is not None and (
            (direction == "increase" and delta > 0) or (direction == "decrease" and delta < 0)
        )
        valid = bool(
            item.get("name") and item.get("mechanism") and item.get("status") == "documented"
            and 0 <= start_tick < end_tick and direction_ok
        )
        verified.append({
            "name": item.get("name"), "metric": metric, "start_tick": start_tick,
            "end_tick": end_tick, "direction": direction, "start": start,
            "end": end, "delta": delta, "mechanism": item.get("mechanism"),
            "supporting_evidence": item.get("evidence", {}), "verified": valid,
        })
    distinct = {
        (item["name"], item["metric"], item["start_tick"], item["end_tick"])
        for item in verified if item["verified"]
    }
    return len(distinct) >= 3, {
        "path": str(evidence_path), "run_id": evidence_run_id,
        "documented": verified,
        "distinct_verified": len(distinct),
    }


def evaluate_acceptance(
    db_path: str | Path,
    *,
    experiment_json: str | Path | None = None,
    phenomena_yaml: str | Path | None = None,
) -> dict:
    """Evaluate all production acceptance gates from persisted evidence."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"run database not found: {db}")
    store = Store(str(db), create=False)
    try:
        meta = store.get_meta()
        config = load_json(meta["config_json"], {})
        acceptance = config.get("acceptance", {})
        required_shocks = tuple(
            str(kind) for kind in acceptance.get("required_shocks", REQUIRED_SHOCKS))
        unknown_required = set(required_shocks).difference(REQUIRED_SHOCKS)
        if unknown_required:
            raise ValueError(
                f"unknown acceptance required_shocks: {sorted(unknown_required)}")
        require_oracle_scoring = bool(
            acceptance.get("require_oracle_scoring", True))
        require_experiment = bool(acceptance.get("require_experiment", True))
        require_phenomena = bool(acceptance.get("require_phenomena", True))
        min_ticks = int(acceptance.get("min_ticks", 365))
        min_agents = int(acceptance.get("min_agents", 95))
        max_agents = int(acceptance.get("max_agents", 105))
        max_spend_raw = acceptance.get("max_spend_usd", 200.0)
        max_spend = None if max_spend_raw is None else float(max_spend_raw)
        efficiency_target = float(acceptance.get("efficiency_target_usd", 200.0))
        configured_cap_raw = config.get("budget", {}).get("cap_usd", 200.0)
        configured_cap = None if configured_cap_raw is None else float(configured_cap_raw)
        oracle_p90_limit = int(acceptance.get("oracle_p90_ms", 60_000))
        oracle_min_samples = int(acceptance.get("oracle_min_latency_samples", 5))
        tick = int(meta["tick"])
        status = str(meta["status"])
        living_agent_count = int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1", default=0))
        historical_agent_count = int(store.scalar(
            "SELECT COUNT(*) FROM agents", default=0))
        participant_influenced = bool(meta["participant_influenced"])
        spend = float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))
        providers = {
            str(row["provider"]) for row in store.query("SELECT DISTINCT provider FROM llm_calls")
            if row["provider"]
        }
        real_providers = providers.difference({"scripted", "mock", "replay"})
        forbidden_providers = providers.intersection({"scripted", "mock"})
        reconciled, ledger_diag = Ledger(store).reconcile()
        failures = {
            kind: int(store.scalar("SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0))
            for kind in FAILURE_EVENTS
        }
        provider_incidents = [
            {
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "kind": str(row["kind"]),
                "recovered": int(row["tick"]) <= tick,
            }
            for row in store.query(
                "SELECT id, tick, kind FROM events "
                "WHERE kind IN ('provider_failure','provider_pause') ORDER BY id LIMIT 50"
            )
        ]
        unrecovered_provider_incidents = int(store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind IN ('provider_failure','provider_pause') AND tick>?",
            (tick,), default=0,
        ))
        hard_failures = sum(
            failures[kind] for kind in (
                "reconciliation_failure", "budget_pause", "report_failed",
                "oracle_tool_execution_failed"))
        failure_evidence = {
            "counts": failures,
            "provider_incidents": provider_incidents,
            "recovered_provider_incidents": (
                failures["provider_failure"] + failures["provider_pause"]
                - unrecovered_provider_incidents
            ),
            "unrecovered_provider_incidents": unrecovered_provider_incidents,
        }
        oracle_schedule = acceptance_schedule_status(store, config, target_tick=min_ticks)
        if _scheduled_e2e_enabled(config):
            oracle_latencies = [
                int(item["latency_ms"])
                for item in oracle_schedule["checkpoints"]
                if item.get("status") == "completed"
                and isinstance(item.get("latency_ms"), int)
            ]
            oracle_latency_source = SCHEDULED_E2E_LATENCY_KIND
        else:
            oracle_latencies = [
                int(row["latency_ms"]) for row in store.query(
                    "SELECT latency_ms FROM llm_calls "
                    "WHERE purpose='oracle' AND latency_ms IS NOT NULL"
                )
            ]
            oracle_latency_source = "answer_call_legacy"
        oracle_p90 = _p90(oracle_latencies)
        oracle_schedule_ok = (
            not oracle_schedule["missed"]
            and all(item["status"] == "completed" for item in oracle_schedule["checkpoints"])
        )
        resolved_predictions = int(store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE status='resolved' AND brier IS NOT NULL", default=0
        ))
        effects, effect_evidence = _shock_effects(store)
        rumor_ok, rumor_evidence = _rumor_pilot(store)
        effect_evidence["traces"]["rumor"].update({
            "downstream": rumor_evidence, "passed": rumor_ok,
        })
        shock_traces_ok = (
            all(kind in effect_evidence["traces"] for kind in required_shocks)
            and all(
                trace.get("source") and trace.get("downstream") and trace.get("passed")
                for kind, trace in effect_evidence["traces"].items()
                if kind in required_shocks
            )
        )
        experiment_ok, experiment_evidence = _experiment_evidence(experiment_json)
        phenomena_ok, phenomena_evidence = _phenomena_evidence(store, phenomena_yaml)

        checks = [
            _check("run_horizon", f"Configured {min_ticks}-tick run completed cleanly",
                   tick >= min_ticks and status in {"paused", "finished"},
                   {"tick": tick, "minimum": min_ticks, "status": status}),
            _check("population", "Production population is approximately 100 living agents",
                   min_agents <= living_agent_count <= max_agents,
                   {"agents": living_agent_count,
                    "living_agents": living_agent_count,
                    "historical_total_agents": historical_agent_count,
                    "range": [min_agents, max_agents]}),
            _check("observer_integrity", "No participant actions contaminated the observer-only run",
                   not participant_influenced,
                   {"participant_influenced": participant_influenced}),
            _check("real_providers", "Run used only configured real providers",
                   bool(real_providers) and not forbidden_providers,
                   {"providers": sorted(providers), "real": sorted(real_providers),
                    "forbidden": sorted(forbidden_providers)}),
            _check("budget", "Provider spend policy was satisfied",
                   (max_spend is None or spend <= max_spend)
                   and (configured_cap is None or spend <= configured_cap),
                   {"spend_usd": round(spend, 6), "maximum_usd": max_spend,
                     "configured_cap_usd": configured_cap,
                     "uncapped": max_spend is None and configured_cap is None}),
            _check(
                   "efficiency_target",
                   f"Provider spend stayed within the ${efficiency_target:g} efficiency target",
                   tick >= min_ticks and spend <= efficiency_target,
                   {"spend_usd": round(spend, 6), "target_usd": efficiency_target,
                    "completed_ticks": tick, "required_ticks": min_ticks}),
            _check("ledger", "Double-entry ledger reconciles exactly", reconciled, ledger_diag),
            _check("failure_events",
                   "No unrecovered provider, budget, report, or reconciliation failure remains",
                   not hard_failures and not unrecovered_provider_incidents and status != "halted",
                   failure_evidence),
            _check("oracle_latency", "Oracle p90 response latency is below 60 seconds",
                   len(oracle_latencies) >= oracle_min_samples
                   and oracle_p90 is not None and oracle_p90 < oracle_p90_limit,
                   {"samples": len(oracle_latencies), "p90_ms": oracle_p90,
                    "minimum_samples": oracle_min_samples,
                    "limit_ms": oracle_p90_limit,
                    "latency_source": oracle_latency_source}),
            _check("oracle_schedule", "Every configured Oracle checkpoint ran at its exact tick",
                   oracle_schedule_ok, oracle_schedule),
            _check("oracle_scoring", "At least one Oracle prediction resolved automatically",
                   not require_oracle_scoring or resolved_predictions > 0,
                   {"resolved_predictions": resolved_predictions,
                    "required": require_oracle_scoring}),
            _check("required_shocks", "All configured required shock types fired",
                   set(effect_evidence["fired_ticks"]) >= set(required_shocks),
                   {"required": list(required_shocks),
                    "fired_ticks": effect_evidence["fired_ticks"]}),
            _check("shock_traces", "Required shocks have explicit source-to-downstream traces",
                   shock_traces_ok, effect_evidence["traces"]),
            _check("policy_rate_effect", "Policy-rate shock changed the policy-rate channel",
                   "policy_rate" not in required_shocks or effects["policy_rate"],
                   effect_evidence if "policy_rate" in required_shocks else {"required": False}),
            _check("oil_effect", "Oil shock changed the commodity-price channel",
                   "oil" not in required_shocks or effects["oil"],
                   effect_evidence if "oil" in required_shocks else {"required": False}),
            _check("rumor_pilot", "Rumor pilot passed conversation, trust, and outflow thresholds",
                   "rumor" not in required_shocks or rumor_ok,
                   rumor_evidence if "rumor" in required_shocks else {"required": False}),
            _check("slant_effect", "Slant directive produced a directed article",
                   "slant" not in required_shocks or effects["slant"],
                   effect_evidence if "slant" in required_shocks else {"required": False}),
            _check("scandal_effect", "Firm scandal was cited by a published article",
                   "scandal" not in required_shocks or effects["scandal"],
                   effect_evidence if "scandal" in required_shocks else {"required": False}),
            _check("experiment_n5", "Five-seed treatment/control experiment completed and reconciled",
                   not require_experiment or experiment_ok,
                   experiment_evidence if require_experiment else {"required": False}),
            _check("emergent_phenomena", "Three emergent phenomena have verified metric signatures",
                   not require_phenomena or phenomena_ok,
                   phenomena_evidence if require_phenomena else {"required": False}),
        ]
        return {
            "schema_version": 3,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {"run_id": str(meta["run_id"]), "database": str(db), "seed": int(meta["seed"])},
            "requirements": {
                "required_shocks": list(required_shocks),
                "require_oracle_scoring": require_oracle_scoring,
                "require_experiment": require_experiment,
                "require_phenomena": require_phenomena,
            },
            "progress": {
                "completed_ticks": tick,
                "required_ticks": min_ticks,
                "fraction": min(1.0, tick / max(1, min_ticks)),
                "actual_spend_usd": round(spend, 6),
                "projected_spend_usd": (
                    round(spend / tick * min_ticks, 6) if tick > 0 else None),
                "efficiency_target_usd": efficiency_target,
                "oracle_latency_samples": len(oracle_latencies),
                "oracle_min_latency_samples": oracle_min_samples,
            },
            "orchestration": oracle_schedule,
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
        }
    finally:
        store.close()


def write_acceptance_package(
    db_path: str | Path,
    *,
    out_dir: str | Path = "reports/out",
    experiment_json: str | Path | None = None,
    phenomena_yaml: str | Path | None = None,
) -> dict:
    receipt = evaluate_acceptance(
        db_path, experiment_json=experiment_json, phenomena_yaml=phenomena_yaml
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = receipt["run"]["run_id"]
    json_path = out / f"acceptance_{run_id}.json"
    md_path = out / f"acceptance_{run_id}.md"
    json_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    lines = [
        f"# Production acceptance — {run_id}", "",
        f"Overall: **{'PASS' if receipt['passed'] else 'FAIL'}**", "", "## Gates", "",
    ]
    for check in receipt["checks"]:
        lines.append(f"- [{'x' if check['passed'] else ' '}] **{check['label']}** (`{check['id']}`)")
        lines.append(f"  - Evidence: `{json.dumps(check['evidence'], sort_keys=True)}`")

    trace_check = next(check for check in receipt["checks"] if check["id"] == "shock_traces")
    lines += ["", "## Shock traces", ""]
    for kind in receipt.get("requirements", {}).get(
            "required_shocks", REQUIRED_SHOCKS):
        trace = trace_check["evidence"].get(kind, {})
        lines += [
            f"### {kind.replace('_', ' ').title()}", "",
            f"- Trace passed: **{'yes' if trace.get('passed') else 'no'}**",
            f"- Source: `{json.dumps(trace.get('source'), sort_keys=True)}`",
            f"- Downstream: `{json.dumps(trace.get('downstream'), sort_keys=True)}`", "",
        ]

    phenomena_check = next(
        check for check in receipt["checks"] if check["id"] == "emergent_phenomena"
    )
    lines += ["## Emergent phenomena", ""]
    for phenomenon in phenomena_check["evidence"].get("documented", []):
        lines += [
            f"### {phenomenon.get('name') or 'Unnamed phenomenon'}", "",
            (f"- Metric: `{phenomenon.get('metric')}` from tick "
             f"{phenomenon.get('start_tick')} to {phenomenon.get('end_tick')}"),
            (f"- Observed change: {phenomenon.get('start')} -> {phenomenon.get('end')} "
             f"(delta {phenomenon.get('delta')})"),
            f"- Mechanism: {phenomenon.get('mechanism')}",
            ("- Supporting evidence: `"
             f"{json.dumps(phenomenon.get('supporting_evidence', {}), sort_keys=True)}`"),
            f"- Verified: **{'yes' if phenomenon.get('verified') else 'no'}**", "",
        ]
    lines += ["", "## Reproduction", "", f"Database: `{receipt['run']['database']}`",
              f"Receipt JSON: `{json_path}`"]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {**receipt, "artifacts": {"json": str(json_path), "markdown": str(md_path)}}


def _has_usable_oracle_evidence(
    store: Store, question: str, asked_tick: int | None = None,
    *, item: dict | None = None, strict: bool = False,
) -> bool:
    if asked_tick is None:
        row = store.query_one(
            "SELECT * FROM predictions WHERE question=? ORDER BY id DESC LIMIT 1",
            (question,))
    else:
        row = store.query_one(
            "SELECT * FROM predictions WHERE question=? AND asked_tick=? "
            "ORDER BY id DESC LIMIT 1", (question, asked_tick))
    valid, _ = _valid_scheduled_prediction(
        store, row, item or {
            "at_tick": asked_tick if asked_tick is not None else row["asked_tick"] if row else -1,
            "question": question,
        }, strict=strict)
    return valid


class AcceptanceCheckpointMissed(RuntimeError):
    """Raised when a prospective Oracle checkpoint cannot be reconstructed honestly."""


def acceptance_schedule_status(store: Store, config: dict, *, target_tick: int | None = None) -> dict:
    """Return persisted, exact-tick Oracle checkpoint progress without changing the run."""
    acceptance = config.get("acceptance", {})
    horizon = int(target_tick or acceptance.get("min_ticks", 365))
    questions = sorted(
        acceptance.get("oracle_questions", []), key=lambda item: int(item["at_tick"]))
    strict = _scheduled_e2e_enabled(config)
    _validate_scheduled_campaign(acceptance, questions)
    checkpoints = []
    for item in questions:
        scheduled_tick = int(item["at_tick"])
        if scheduled_tick > horizon:
            continue
        question = str(item["question"])
        persisted = store.query_one(
            "SELECT status,detail,prediction_id FROM acceptance_checkpoints "
            "WHERE scheduled_tick=? AND question=?", (scheduled_tick, question))
        prediction = None
        if persisted and persisted["prediction_id"] is not None:
            prediction = store.query_one(
                "SELECT * FROM predictions WHERE id=? AND question=? AND asked_tick=?",
                (int(persisted["prediction_id"]), question, scheduled_tick))
        if prediction is None:
            prediction = store.query_one(
                "SELECT * FROM predictions WHERE question=? AND asked_tick=? "
                "ORDER BY id DESC LIMIT 1", (question, scheduled_tick))
        usable, validation_error = _valid_scheduled_prediction(
            store, prediction, item, strict=strict)
        completion = None
        completion_error = None
        if strict and usable and prediction is not None:
            completion, completion_error = _completion_latency(
                store, prediction_id=int(prediction["id"]), item=item,
                acceptance=acceptance)
        completed = usable and (not strict or completion is not None)
        status = "completed" if completed else (
            "missed" if store.tick > scheduled_tick or (persisted and persisted["status"] == "missed")
            else "pending")
        checkpoints.append({
            "scheduled_tick": scheduled_tick, "question": question, "status": status,
            "campaign_key": _scheduled_question_key(item) if strict else None,
            "prediction_id": int(prediction["id"]) if prediction and completed else None,
            "detail": persisted["detail"] if persisted else None,
            "validation_error": validation_error or completion_error,
            "latency_ms": completion["latency_ms"] if completion else None,
            "latency_kind": completion["latency_kind"] if completion else None,
            "completion_event_id": completion["event_id"] if completion else None,
        })
    missed = [item for item in checkpoints if item["status"] == "missed"]
    pending = [item for item in checkpoints if item["status"] == "pending"]
    state = "invalid" if missed else (
        "completed" if store.tick >= horizon and not pending else "pending")
    return {
        "state": state, "target_tick": horizon, "completed_tick": store.tick,
        "next_checkpoint": pending[0] if pending else None,
        "checkpoints": checkpoints, "missed": missed,
    }


def _record_checkpoint(
    store: Store, scheduled_tick: int, question: str, status: str,
    *, prediction_id: int | None = None, detail: str | None = None,
) -> None:
    existing = store.query_one(
        "SELECT status,prediction_id,detail FROM acceptance_checkpoints "
        "WHERE scheduled_tick=? AND question=?", (scheduled_tick, question))
    if existing is not None and (
        str(existing["status"]) == status
        and existing["prediction_id"] == prediction_id
        and existing["detail"] == detail
    ):
        # Preserve the original completed_at value and make repeated orchestration
        # a true no-op instead of a timestamp-only mutation.
        return
    completed_at = datetime.now(timezone.utc).isoformat() if status == "completed" else None
    store.execute(
        "INSERT INTO acceptance_checkpoints(scheduled_tick,question,status,prediction_id,detail,completed_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(scheduled_tick,question) DO UPDATE SET "
        "status=excluded.status,prediction_id=excluded.prediction_id,detail=excluded.detail,"
        "completed_at=excluded.completed_at",
        (scheduled_tick, question, status, prediction_id, detail, completed_at))
    store.commit()


def _finalize_scheduled_checkpoint(
    store: Store, *, item: dict, acceptance: dict, prediction_id: int,
    latency_ms: int, model_calls: list[dict], latency_measurement: str,
) -> None:
    """Append exactly one completion event, then idempotently bind its checkpoint."""
    tick = int(item["at_tick"])
    question = str(item["question"])
    payload: dict[str, Any] = {
        "scheduled_tick": tick,
        "question": question,
        "prediction_id": prediction_id,
        "latency_ms": int(latency_ms),
        "latency_kind": SCHEDULED_E2E_LATENCY_KIND,
        "latency_measurement": latency_measurement,
        "campaign_id": acceptance["oracle_campaign_id"],
        "campaign_version": acceptance["oracle_campaign_version"],
        "campaign_key": _scheduled_question_key(item),
        "model_calls": model_calls,
    }
    bound = []
    for row in store.query(
        "SELECT id,payload_json FROM events "
        "WHERE kind='acceptance_checkpoint_completed' AND tick=? ORDER BY id",
        (tick,),
    ):
        existing_payload = load_json(row["payload_json"], {})
        if not isinstance(existing_payload, dict):
            continue
        if (
            existing_payload.get("prediction_id") == prediction_id
            or (
                existing_payload.get("scheduled_tick") == tick
                and existing_payload.get("question") == question
                and existing_payload.get("campaign_key") == _scheduled_question_key(item)
            )
        ):
            bound.append((int(row["id"]), existing_payload))
    if len(bound) > 1:
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {tick} has duplicate completion events")
    if bound:
        _event_id, existing_payload = bound[0]
        if existing_payload != payload:
            # A completion event is release evidence, not an updatable status
            # row.  Never overwrite or add a conflicting sample on resume.
            completion, error = _completion_latency(
                store, prediction_id=prediction_id, item=item, acceptance=acceptance)
            if completion is None:
                raise AcceptanceCheckpointMissed(
                    f"Oracle checkpoint at tick {tick} has invalid completion evidence: "
                    f"{error}")
    else:
        store.log_event(
            tick, "acceptance_checkpoint_completed", payload,
            phase="CONTROL", importance=2.0)
    _record_checkpoint(
        store, tick, question, "completed", prediction_id=prediction_id)


def _record_missed_checkpoint(
    store: Store, *, scheduled_tick: int, question: str, detail: str,
    event_tick: int, prediction_id: int | None = None,
) -> None:
    """Persist a missed checkpoint and its diagnostic event exactly once."""
    expected_payload: dict[str, Any] = {
        "scheduled_tick": scheduled_tick,
        "question": question,
        "detail": detail,
    }
    if prediction_id is not None:
        expected_payload["prediction_id"] = prediction_id
    bound = []
    for row in store.query(
        "SELECT id,tick,payload_json FROM events "
        "WHERE kind='acceptance_checkpoint_missed' ORDER BY id",
    ):
        payload = load_json(row["payload_json"], {})
        if (isinstance(payload, dict)
                and payload.get("scheduled_tick") == scheduled_tick
                and payload.get("question") == question):
            bound.append((int(row["id"]), int(row["tick"]), payload))
    if len(bound) > 1:
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {scheduled_tick} has duplicate missed events")
    if bound and bound[0][2] != expected_payload:
        raise AcceptanceCheckpointMissed(
            f"Oracle checkpoint at tick {scheduled_tick} has conflicting missed evidence")
    _record_checkpoint(
        store, scheduled_tick, question, "missed", detail=detail)
    if not bound:
        store.log_event(
            event_tick, "acceptance_checkpoint_missed", expected_payload,
            phase="CONTROL", importance=5.0)
    store.commit()


async def advance_acceptance_run(
    world: "World", *, target_tick: int | None = None,
) -> dict:
    """Advance until the horizon or a safe pause, enforcing exact Oracle checkpoints."""
    acceptance = world.config.get("acceptance", {})
    horizon = int(target_tick or acceptance.get("min_ticks", 365))
    questions = sorted(
        acceptance.get("oracle_questions", []), key=lambda item: int(item["at_tick"]))
    strict = _scheduled_e2e_enabled(world.config)
    _validate_scheduled_campaign(acceptance, questions)
    for item in questions:
        at_tick = int(item["at_tick"])
        if at_tick > horizon:
            continue
        question = str(item["question"])
        existing = world.store.query_one(
            "SELECT * FROM predictions WHERE question=? AND asked_tick=? ORDER BY id DESC LIMIT 1",
            (question, at_tick))
        existing_valid, _ = _valid_scheduled_prediction(
            world.store, existing, item, strict=strict)
        existing_completion = None
        existing_completion_error = None
        if strict and existing_valid and existing is not None:
            existing_completion, existing_completion_error = _completion_latency(
                world.store, prediction_id=int(existing["id"]), item=item,
                acceptance=acceptance)
        if existing_valid and (not strict or existing_completion is not None):
            _record_checkpoint(world.store, at_tick, question, "completed",
                               prediction_id=int(existing["id"]))
            continue
        if strict and existing_valid and existing is not None:
            if existing_completion_error != (
                    "prediction has no bound scheduled completion event"):
                detail = (
                    f"Oracle checkpoint at tick {at_tick} has invalid completion "
                    f"evidence: {existing_completion_error}")
                _record_missed_checkpoint(
                    world.store, scheduled_tick=at_tick, question=question,
                    detail=detail, event_tick=world.store.tick,
                    prediction_id=int(existing["id"]))
                raise AcceptanceCheckpointMissed(detail)
            model_calls, call_error = _scheduled_call_evidence(
                world.store, item=item, acceptance=acceptance)
            if call_error:
                detail = (
                    f"Oracle checkpoint at tick {at_tick} has a prediction without "
                    f"complete governed call evidence: {call_error}")
                _record_missed_checkpoint(
                    world.store, scheduled_tick=at_tick, question=question,
                    detail=detail, event_tick=world.store.tick,
                    prediction_id=int(existing["id"]))
                raise AcceptanceCheckpointMissed(detail)
            try:
                started_epoch_ns, _ = _scheduled_timer_marker(
                    world.store, item=item, acceptance=acceptance, create=False)
            except AcceptanceCheckpointMissed as exc:
                detail = str(exc)
                _record_missed_checkpoint(
                    world.store, scheduled_tick=at_tick, question=question,
                    detail=detail, event_tick=world.store.tick,
                    prediction_id=int(existing["id"]))
                raise
            _finalize_scheduled_checkpoint(
                world.store, item=item, acceptance=acceptance,
                prediction_id=int(existing["id"]),
                latency_ms=_resumed_scheduled_latency_ms(
                    started_epoch_ns, model_calls),
                model_calls=model_calls,
                latency_measurement="resumed_wall_clock",
            )
            continue
        if world.store.tick > at_tick:
            detail = (
                f"Oracle checkpoint at tick {at_tick} was passed without usable evidence; "
                "a late prediction would be contaminated by later world state")
            _record_missed_checkpoint(
                world.store, scheduled_tick=at_tick, question=question,
                detail=detail, event_tick=world.store.tick)
            raise AcceptanceCheckpointMissed(detail)
        if world.store.tick < at_tick:
            await world.run(max_ticks=at_tick - world.store.tick)
            if world.store.tick < at_tick:
                return acceptance_schedule_status(
                    world.store, world.config, target_tick=horizon)
        started_epoch_ns = None
        resumed_timing = False
        if strict:
            try:
                started_epoch_ns, resumed_timing = _scheduled_timer_marker(
                    world.store, item=item, acceptance=acceptance)
            except AcceptanceCheckpointMissed as exc:
                detail = str(exc)
                _record_missed_checkpoint(
                    world.store, scheduled_tick=at_tick, question=question,
                    detail=detail, event_tick=world.store.tick)
                raise
        started_ns = time.perf_counter_ns()
        governed_contract = (
            _scheduled_contract(acceptance, item) if strict else None)
        result = (
            await world.oracle.ask(question, governed_contract=governed_contract)
            if strict else await world.oracle.ask(question)
        )
        prediction_id = result.get("prediction_id") if isinstance(result, dict) else None
        prediction = None
        if isinstance(prediction_id, int) and not isinstance(prediction_id, bool):
            prediction = world.store.query_one(
                "SELECT * FROM predictions WHERE id=? AND question=? AND asked_tick=?",
                (prediction_id, question, at_tick))
        valid, validation_error = _valid_scheduled_prediction(
            world.store, prediction, item, strict=strict)
        if not valid:
            detail = (
                f"Oracle checkpoint at tick {at_tick} produced no usable read evidence: "
                f"{validation_error}")
            _record_missed_checkpoint(
                world.store, scheduled_tick=at_tick, question=question,
                detail=detail, event_tick=at_tick,
                prediction_id=(prediction_id if isinstance(prediction_id, int)
                               and not isinstance(prediction_id, bool) else None))
            raise AcceptanceCheckpointMissed(detail)
        payload: dict[str, Any] = {
            "scheduled_tick": at_tick, "question": question,
            "prediction_id": prediction_id,
        }
        if strict:
            model_calls, call_error = _scheduled_call_evidence(
                world.store, item=item, acceptance=acceptance)
            if call_error:
                detail = (
                    f"Oracle checkpoint at tick {at_tick} produced a prediction "
                    f"without complete governed call evidence: {call_error}")
                _record_missed_checkpoint(
                    world.store, scheduled_tick=at_tick, question=question,
                    detail=detail, event_tick=at_tick,
                    prediction_id=int(prediction_id))
                raise AcceptanceCheckpointMissed(detail)
            if resumed_timing:
                latency_ms = _resumed_scheduled_latency_ms(
                    int(started_epoch_ns), model_calls)
                latency_measurement = "resumed_wall_clock"
            else:
                latency_ms = max(
                    0, math.ceil(
                        (time.perf_counter_ns() - started_ns) / 1_000_000))
                latency_measurement = "continuous_monotonic"
            _finalize_scheduled_checkpoint(
                world.store, item=item, acceptance=acceptance,
                prediction_id=int(prediction_id), latency_ms=latency_ms,
                model_calls=model_calls,
                latency_measurement=latency_measurement,
            )
        else:
            world.store.log_event(
                at_tick, "acceptance_checkpoint_completed", payload,
                phase="CONTROL", importance=2.0)
            _record_checkpoint(
                world.store, at_tick, question, "completed",
                prediction_id=int(prediction_id))
    if world.store.tick < horizon:
        await world.run(max_ticks=horizon - world.store.tick)
    return acceptance_schedule_status(world.store, world.config, target_tick=horizon)


async def execute_acceptance_run(world: "World", *, target_tick: int | None = None) -> None:
    """Headless compatibility wrapper: a pause remains a non-zero completion failure."""
    status = await advance_acceptance_run(world, target_tick=target_tick)
    if status["state"] != "completed":
        raise RuntimeError(
            f"acceptance run paused at tick {world.store.tick}; target was {status['target_tick']}")
