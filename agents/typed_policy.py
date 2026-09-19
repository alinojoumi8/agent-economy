"""Bounded choice policy; providers select IDs and never construct engine actions."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json

from llm.decision_config import POLICY_VERSION, decision_policy
from llm.decisions import decision_hash
from llm.gateway import LLMRequest, LLMResponse
from .decision_candidates import COMPILER_VERSION, DecisionMenu, compile_candidates


@dataclass
class TypedDecision:
    envelope: dict
    response: LLMResponse | None
    receipt: dict
    suppress_reasoning: bool = True


class TypedDecisionPolicy:
    def __init__(self, gateway, config: dict):
        self.gateway = gateway
        self.policy = decision_policy(config)
        self.seed = int(config.get("seed", 0))

    def prepare(self, context: dict, tick: int) -> DecisionMenu | None:
        policy = self.policy
        if policy is None or tick < policy["activation_tick"] or context.get("purpose") != "decision":
            return None
        agent_id = context["agent"]["id"]
        plan = context.get("compute_plan") or {}
        tier = str(plan.get("tier", "legacy"))
        if tier not in policy["eligible_tiers"]:
            return None
        assignment = int(decision_hash({"seed": self.seed, "agent": agent_id, "policy": POLICY_VERSION})[:16], 16)
        if assignment / 2**64 >= policy["population_fraction"]:
            return None
        return compile_candidates(context, tick, policy)

    def _call_receipt(self, response: LLMResponse) -> dict:
        row = self.gateway.store.query_one("SELECT latency_ms,response_json FROM llm_calls WHERE id=?",
                                           (response.call_id,))
        typed = response.parsed if isinstance(response.parsed, dict) else {}
        raw = json.loads(row["response_json"] or "{}") if row else {}
        return {"model_call_id": response.call_id, "provider": response.provider,
                "requested_model": response.model, "resolved_model": typed.get("model"),
                "upstream_provider": typed.get("provider"), "request_id": typed.get("id"),
                "cost_usd": response.cost_usd, "input_tokens": response.in_tokens,
                "output_tokens": response.out_tokens, "latency_ms": int(row["latency_ms"] or 0) if row else 0,
                "cost_basis": (raw.get("raw") or {}).get("cost_basis", "declared_tariff")}

    async def complete(self, request: LLMRequest, menu: DecisionMenu) -> TypedDecision:
        receipt = {"contract": POLICY_VERSION, "compiler": COMPILER_VERSION,
                   "agent_id": request.agent_id, "tick": request.tick, "purpose": request.purpose,
                   "observation_hash": menu.observation_hash, "menu_hash": menu.menu_hash,
                   "candidates": menu.candidates, "calls": [], "confidence": None,
                   "evaluation": menu.evaluation, "baseline_choice": menu.baseline_choice,
                   "confidence_meaning": "answer_distribution_concentration",
                   "escalated": False, "selected_candidate": None}
        receipt["receipt_key"] = decision_hash({key: receipt[key] for key in (
            "contract", "agent_id", "tick", "purpose", "observation_hash", "menu_hash")})
        if menu.unsupported_reason:
            # This is an explicit capability boundary, shared by every matched
            # arm, rather than a failed-provider fallback. Keep the existing role
            # policy and all of its real background behavior intact.
            response = await self.gateway.complete(request)
            receipt.update(status="outside_menu", reason=menu.unsupported_reason,
                           calls=[self._call_receipt(response)])
            return TypedDecision(dict(response.parsed), response, receipt, suppress_reasoning=False)
        response = None
        if len(menu.candidates) == 2:
            choice, status, reason = "wait", "no_candidates", "no_eligible_shopping_or_job_action"
        elif self.policy["primary"]["provider"] == "scripted":
            choice, status, reason = menu.baseline_choice, "selected", "deterministic_menu_baseline"
        else:
            request = replace(request, max_tokens=self.policy["max_output_tokens"])
            response = await self.gateway.evaluate(request, menu.evaluation)
            receipt["calls"].append(self._call_receipt(response))
            answer = response.parsed["answers"]["action"]
            choice, confidence = answer["choice"], answer.get("confidence")
            receipt["confidence"] = confidence
            threshold = self.policy["minimum_confidence"]
            reason = ("unsupported_choice" if choice == "escalate" else
                      "missing_confidence" if threshold > 0 and confidence is None else
                      "low_confidence" if confidence is not None and confidence < threshold else "provider_choice")
            status = "selected"
            if reason != "provider_choice":
                if self.policy["on_abstain"] == "escalate":
                    response = await self.gateway.evaluate(request, menu.evaluation, route="escalation")
                    receipt["calls"].append(self._call_receipt(response))
                    receipt["escalated"] = True
                    choice = response.parsed["answers"]["action"]["choice"]
                    status = "escalated" if choice != "escalate" else "abstained"
                else:
                    status = "abstained"
                if status == "abstained":
                    choice = "wait"
        receipt.update(status=status, reason=reason, selected_candidate=choice)
        return TypedDecision({"reasoning": "", "actions": menu.actions_for(choice), "belief_updates": []},
                             response, receipt)


def record_execution_receipt(store, tick: int, decision: dict, results: list[dict]) -> None:
    receipt = decision.get("typed_receipt")
    if receipt is None:
        return
    payload = {**receipt, "outcomes": [{"ok": result.get("ok") is True,
                "reason": str(result.get("reason") or "")[:300]} for result in results]}
    existing = store.query_one(
        "SELECT payload_json FROM events WHERE tick=? AND kind='typed_decision' AND subject_id=? "
        "AND json_extract(payload_json,'$.receipt_key')=? ORDER BY id LIMIT 1",
        (tick, decision["agent_id"], receipt["receipt_key"]))
    if existing:
        if json.loads(existing["payload_json"]) != payload:
            raise RuntimeError("typed decision execution receipt changed on retry")
        return
    store.log_event(tick, "typed_decision", payload, phase="EXECUTION", subject_type="agent",
                    subject_id=decision["agent_id"], importance=1.0)
