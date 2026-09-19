"""Versioned typed evaluation contracts, independent of world mutation.

These validators are shared by transport, recorded replay and offline evaluation.
They deliberately do not interpret confidence as the chance an action succeeds.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


DECISIONS_CONTRACT = "agent-economy-decisions-v1"
MAX_REQUEST_BYTES = 31_488  # Conservative UTF-8 bound within the 32K context.
MAX_RESPONSE_BYTES = 262_144
MAX_QUESTIONS = 32


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def decision_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def finite_number(value: Any, low: float, high: float) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and low <= value <= high


def validate_evaluation(value: Any) -> dict:
    """Return a detached bounded request; reject extras before network admission."""
    if not isinstance(value, dict) or set(value) != {"state", "questions"}:
        raise ValueError("evaluation requires exactly state and questions")
    if not isinstance(value["state"], (str, dict, list)):
        raise ValueError("evaluation state must be text, an object, or an array")
    questions = value["questions"]
    if not isinstance(questions, dict) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ValueError("evaluation requires one to 32 named questions")
    for key, question in questions.items():
        if not isinstance(key, str) or not key or len(key) > 100:
            raise ValueError("question identifiers must be bounded nonempty strings")
        if not isinstance(question, dict) or set(question) - {"type", "instructions", "criteria"}:
            raise ValueError("question has unsupported fields")
        if not isinstance(question.get("instructions"), str) or not question["instructions"].strip():
            raise ValueError("question instructions are required")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "choice":
            if (not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255
                    or any(not isinstance(k, str) or not k or len(k) > 100 for k in criteria)):
                raise ValueError("choice requires two to 255 distinct bounded option IDs")
        elif kind == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 255:
                raise ValueError("score requires an ordered rubric of two to 255 entries")
        elif kind == "noul":
            if criteria is not None and (not isinstance(criteria, dict) or set(criteria) != {"false", "true"}):
                raise ValueError("noul criteria must describe false and true")
        else:
            raise ValueError("unsupported evaluation question type")
        guidance = criteria.values() if isinstance(criteria, dict) else criteria or []
        if any(not isinstance(item, (str, dict, list)) for item in guidance):
            raise ValueError("criteria must contain text or structured guidance")
    encoded = canonical_json(value)
    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("evaluation exceeds the conservative 32K input allowance")
    return json.loads(encoded)


def answer_error(value: Any, evaluation: dict) -> str | None:
    """Validate the exact question/option binding, without requiring optional fields."""
    if not isinstance(value, dict) or not isinstance(value.get("answers"), dict):
        return "evaluation response requires named answers"
    if set(value["answers"]) != set(evaluation["questions"]):
        return "evaluation answer IDs differ from the requested questions"
    for key, question in evaluation["questions"].items():
        answer = value["answers"][key]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            return "evaluation answer type differs from the question"
        allowed = {"type", "choice", "confidence", "probabilities"} if kind == "choice" else (
            {"type", "score", "confidence", "probabilities", "legend"} if kind == "score" else {"type", "noul"})
        if set(answer) - allowed:
            return "evaluation answer contains undeclared fields"
        if kind == "noul":
            if not finite_number(answer.get("noul"), 0, 1):
                return "noul must be a finite probability"
            continue
        if kind == "choice":
            if not isinstance(answer.get("choice"), str) or answer["choice"] not in question["criteria"]:
                return "selected option is absent from the supplied menu"
            options = set(question["criteria"])
        else:
            if not finite_number(answer.get("score"), 0, len(question["criteria"]) - 1):
                return "score is outside the supplied rubric"
            options = {str(i) for i in range(len(question["criteria"]))}
            if "legend" in answer and answer["legend"] != dict(enumerate(question["criteria"])):
                expected = {str(i): item for i, item in enumerate(question["criteria"])}
                if answer["legend"] != expected:
                    return "score legend differs from the supplied rubric"
        if "confidence" in answer and not finite_number(answer["confidence"], 0, 1):
            return "confidence must be finite and between zero and one"
        if "probabilities" in answer:
            probabilities = answer["probabilities"]
            if (not isinstance(probabilities, dict) or set(probabilities) != options
                    or any(not finite_number(p, 0, 1) for p in probabilities.values())
                    or abs(sum(probabilities.values()) - 1) > .02):
                return "answer distribution is malformed or not bound to all options"
    return None


def response_error(value: Any, evaluation: dict, *, expected_models: tuple[str, ...] = (),
                   expected_provider: str | None = None) -> str | None:
    error = answer_error(value, evaluation)
    if error:
        return error
    if not isinstance(value.get("model"), str) or not value["model"]:
        return "evaluation response has no resolved model"
    if expected_models and value["model"] not in expected_models:
        return "resolved evaluation model differs from the declared version"
    if expected_provider and value.get("provider") not in {None, expected_provider}:
        return "evaluation upstream provider differs from the declaration"
    usage = value.get("usage")
    if (not isinstance(usage, dict)
            or any(type(usage.get(k)) is not int or not 0 <= usage[k] <= 2**31 - 1
                   for k in ("input_tokens", "output_tokens"))):
        return "evaluation requires reported integer input and output usage"
    if "cost" in usage and not finite_number(usage["cost"], 0, 1_000_000):
        return "evaluation cost must be finite and nonnegative"
    if value.get("id") is not None and (not isinstance(value["id"], str) or len(value["id"]) > 256):
        return "evaluation response ID is malformed"
    return None
