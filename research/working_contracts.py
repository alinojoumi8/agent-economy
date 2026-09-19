"""Versioned working-study policies and phase/input evidence.

Position hashes describe private execution state. Public projections expose
only completed/active days and the next phase, never queued decisions.
"""
from __future__ import annotations

import hashlib
import json
import random

from research.artifacts import digest_json
from world.phases import phase_names_for_semantics


DAY_PROTOCOL = "working-attempt-v2"
PHASE_PROTOCOL = "working-attempt-v3"
POLICIES = {"preserve_and_resume": DAY_PROTOCOL,
            "preserve_and_resume_phases": PHASE_PROTOCOL}
POSITION_CONTRACT = "working-phase-position-v1"


def working_protocol(policy: str) -> str | None:
    return POLICIES.get(policy)


def attempt_version(study: dict) -> int:
    if study.get("protocol_version") == "research-study-v3" and study.get("origin") is not None:
        return 6
    if study.get("protocol_version") == "research-study-v3" and working_protocol(study["operations"]["pause_policy"]):
        return 5
    if study.get("origin") is not None:
        return 4
    protocol = working_protocol(study["operations"]["pause_policy"])
    return 3 if protocol == PHASE_PROTOCOL else 2 if protocol else 1


def claim_working_protocol(claim: dict) -> str | None:
    if claim.get("protocol_version") in {5, 6} and claim.get("study_manifest", {}).get("study", {}).get("protocol_version") != "research-study-v3":
        raise ValueError("policy working claims require a v3 study")
    if claim.get("protocol_version") in {2, 3, 4, 5, 6}:
        return working_protocol(claim["study_manifest"]["study"]["operations"]["pause_policy"])
    return None


def phase_controls(policy: str, semantics: int, *, ticks: int | None, phase: str | None) -> None:
    if phase is not None:
        if working_protocol(policy) != PHASE_PROTOCOL:
            raise ValueError("phase pause requires the preserve_and_resume_phases policy")
        if phase not in phase_names_for_semantics(semantics):
            raise ValueError("pause phase is not supported by these engine semantics")
        if ticks is not None:
            raise ValueError("choose a day limit or a phase pause, not both")


def input_prefixes(store, end_ids: set[int]) -> dict[int, dict]:
    """Hash requested immutable recorded-call prefixes with a single scan."""
    digest, count = hashlib.sha256(), 0
    result = {0: {"count": 0, "last_id": 0, "sha256": digest.hexdigest()}}
    if not end_ids or max(end_ids) == 0:
        return result
    for row in store.conn.execute("SELECT * FROM llm_calls WHERE id<=? ORDER BY id", (max(end_ids),)):
        digest.update(digest_json(dict(row)).encode("ascii") + b"\n")
        count += 1
        last_id = int(row["id"])
        if last_id in end_ids:
            result[last_id] = {"count": count, "last_id": last_id, "sha256": digest.hexdigest()}
    if end_ids - set(result):
        raise ValueError("recorded input prefix is missing")
    return result


def _integer(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid phase position {label}")
    return value


def position_rank(position: dict, semantics: int, horizon: int) -> int:
    if not isinstance(position, dict) or set(position) != {"contract", "completed_tick", "active_tick", "next_phase", "phase_state_sha256",
                         "prng_sha256", "recorded_inputs"} or position["contract"] != POSITION_CONTRACT:
        raise ValueError("invalid working phase position contract")
    phases = phase_names_for_semantics(semantics)
    tick = _integer(position["completed_tick"], "completed day")
    active = position["active_tick"]
    if tick > horizon or position["next_phase"] not in phases:
        raise ValueError("phase position exceeds the declared horizon or phases")
    if active is None:
        if position["next_phase"] != "NIGHT_CLOSE":
            raise ValueError("closed day has an unfinished phase")
        rank = tick * len(phases)
    else:
        if _integer(active, "active day") != tick + 1 or active > horizon:
            raise ValueError("active day does not follow the completed day")
        rank = tick * len(phases) + phases.index(position["next_phase"])
    inputs = position["recorded_inputs"]
    if not isinstance(inputs, dict) or set(inputs) != {"count", "last_id", "sha256"}:
        raise ValueError("invalid recorded input prefix")
    if _integer(inputs["count"], "input count") > _integer(inputs["last_id"], "last input id"):
        raise ValueError("invalid recorded input sequence")
    if (inputs["count"] == 0) != (inputs["last_id"] == 0):
        raise ValueError("invalid empty recorded input prefix")
    for value in (position["phase_state_sha256"], position["prng_sha256"], inputs["sha256"]):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid phase position digest")
    return rank


def persisted_random_state(meta) -> dict:
    """Validate every stream restored by World before admitting a saved state."""
    try:
        engine = json.loads(meta["prng_state"])
        lifecycle = json.loads(meta["lifecycle_prng_state"])
        if not isinstance(engine, dict) or set(engine) != {"engine", "persona"}:
            raise ValueError("missing engine/persona streams")
        for value in (engine["engine"], engine["persona"], lifecycle):
            if not isinstance(value, list) or len(value) != 3:
                raise ValueError("invalid random state shape")
            random.Random().setstate((value[0], tuple(value[1]), value[2]))
    except (ValueError, TypeError, IndexError, KeyError, OverflowError) as exc:
        raise ValueError("invalid persisted random streams for phase recovery") from exc
    return {"engine_persona": engine, "lifecycle": lifecycle}


def phase_position(store, semantics: int, horizon: int) -> dict:
    """Validate the engine's persisted frontier before any writable reopen."""
    meta = store.get_meta()
    if meta["status"] != "paused" or meta["legacy_partial"]:
        raise ValueError("phase recovery requires an explicit modern paused frontier")
    phases = phase_names_for_semantics(semantics)
    active, phase = meta["active_tick"], meta["next_phase"]
    state = json.loads(meta["phase_state_json"] or "{}")
    if not isinstance(state, dict) or set(state) - {"decisions", "conversation_pairs", "observations_captured"}:
        raise ValueError("unsupported persisted phase state")
    if active is None:
        if state or phase not in (None, "NIGHT_CLOSE"):
            raise ValueError("closed day retains unfinished phase state")
        phase = "NIGHT_CLOSE"
    else:
        if phase not in phases:
            raise ValueError("unknown persisted phase")
        index = phases.index(phase)
        if index < phases.index("EXECUTION") and "decisions" in state:
            raise ValueError("decisions precede the morning phase")
        if index >= phases.index("EXECUTION") and not isinstance(state.get("decisions"), list):
            raise ValueError("phase is missing its saved decisions")
        if "decisions" in state and any(
                not isinstance(item, dict) or type(item.get("agent_id")) is not int
                or item["agent_id"] <= 0 or "envelope" not in item for item in state["decisions"]):
            raise ValueError("invalid saved decision envelope")
        if index < phases.index("EVENING") and "conversation_pairs" in state:
            raise ValueError("conversation plan precedes its phase")
        if index > phases.index("EVENING") and "conversation_pairs" not in state:
            raise ValueError("phase is missing its conversation plan")
        if "conversation_pairs" in state:
            pairs = state["conversation_pairs"]
            if (not isinstance(pairs, list) or any(not isinstance(pair, list) or len(pair) != 2
                    or any(type(aid) is not int or aid <= 0 for aid in pair) or pair[0] == pair[1] for pair in pairs)):
                raise ValueError("invalid saved conversation plan")
        if "observations_captured" in state and (index < phases.index("MEMORY") or type(state["observations_captured"]) is not bool):
            raise ValueError("invalid observation phase marker")
        if index > phases.index("MEMORY") and state.get("observations_captured") is not True:
            raise ValueError("finalization is missing its observation receipt")
    streams = persisted_random_state(meta)
    last_id = int(store.scalar("SELECT COALESCE(MAX(id),0) FROM llm_calls", default=0))
    position = {"contract": POSITION_CONTRACT, "completed_tick": _integer(meta["tick"], "completed day"),
                "active_tick": active, "next_phase": phase,
                "phase_state_sha256": digest_json(state),
                "prng_sha256": digest_json(streams),
                "recorded_inputs": input_prefixes(store, {last_id})[last_id]}
    position_rank(position, semantics, horizon)
    return position


def verify_input_prefixes(store, positions: list[dict]) -> None:
    """Every earlier admitted response must remain byte-for-byte unchanged."""
    expected = [position["recorded_inputs"] for position in positions]
    actual = input_prefixes(store, {item["last_id"] for item in expected})
    if any(item != actual[item["last_id"]] for item in expected):
        raise ValueError("recorded input history changed")


def paused_progress(row: dict, previous: dict | None, claim: dict) -> bool:
    """Day-only receipts stay strict; phase receipts allow receipted same-phase retries."""
    protocol = claim["study_manifest"]["attempt_protocol"]
    if type(row["ticks"]) is not int:
        return False
    origin = claim.get("checkpoint_origin", {}).get("receipt")
    initial_tick = origin["tick"] if origin else 0
    if protocol == DAY_PROTOCOL:
        return row["ticks"] > (previous["ticks"] if previous else initial_tick) and "position" not in row
    if protocol != PHASE_PROTOCOL:
        raise ValueError("unsupported working attempt protocol")
    semantics = claim["study_manifest"]["study"]["model"]["engine_semantics_version"]
    rank = position_rank(row["position"], semantics, claim["expected_ticks"])
    if row["ticks"] != row["position"]["completed_tick"] or row["ticks"] >= claim["expected_ticks"]:
        return False
    if previous is None:
        return (row["ticks"] >= initial_tick and (not origin or
            row["position"]["recorded_inputs"]["count"] >= origin["recorded_inputs"]["count"]
            and row["position"]["recorded_inputs"]["last_id"] >= origin["recorded_inputs"]["last_id"]))
    return (rank >= position_rank(previous["position"], semantics, claim["expected_ticks"])
            and row["position"]["recorded_inputs"]["count"] >= previous["position"]["recorded_inputs"]["count"]
            and row["position"]["recorded_inputs"]["last_id"] >= previous["position"]["recorded_inputs"]["last_id"])
