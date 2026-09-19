"""Read-only, prospective domain menus from recorded authorized request contexts.

Never reconstruct a past observation using final world tables. Incomplete old
contexts are exclusions, not an invitation to infer unknown resources or terms.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from agents.decision_candidates import compile_candidates
from agents.decision_domains import DOMAINS, TYPED_PURPOSES
from llm.decision_config import POLICY_VERSION_V4, decision_policy
from llm.decisions import decision_hash
from research.artifacts import file_sha256, publish_json
from research.decision_studies import PROTOCOL, frozen_menu


def build_counterfactual(database, output, config, domain, limit=200):
    policy = decision_policy(config)
    if not policy or policy["version"] != POLICY_VERSION_V4 or domain not in policy["domains"] or domain not in DOMAINS:
        raise ValueError("counterfactual builder requires an enabled v4 domain")
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("limit must be between one and 100000")
    database = Path(database).resolve()
    if any(Path(str(database) + s).exists() and Path(str(database) + s).stat().st_size for s in ("-wal", "-journal")):
        raise ValueError("close the source before building counterfactual observations")
    source_hash = file_sha256(database)
    conn = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    exclusions, strata, seen = Counter(), defaultdict(list), set()
    try:
        meta = dict(conn.execute("SELECT * FROM run_meta LIMIT 1").fetchone())
        for row in conn.execute("SELECT id,tick,agent_id,purpose,request_json FROM llm_calls WHERE tick<=? ORDER BY tick,id", (meta["tick"],)):
            if row["purpose"] not in TYPED_PURPOSES or row["purpose"] in {"preflight", "decision_evaluation"}:
                continue
            request = json.loads(row["request_json"])
            context = deepcopy(request.get("context"))
            if not isinstance(context, dict) or not {"agent", "state", "tick", "decision_resources"} <= set(context):
                exclusions["incomplete_authorized_context"] += 1
                continue
            context.pop("_evaluation", None)
            if context["agent"].get("id") != row["agent_id"] or context["tick"] != row["tick"]:
                exclusions["actor_or_tick_mismatch"] += 1
                continue
            identity = (row["agent_id"], row["tick"])
            if identity in seen:
                exclusions["duplicate_actor_turn"] += 1
                continue
            seen.add(identity)
            if domain == "founder_operations" and not {"currency_code", "executed_sales_units", "sales_window"} <= set(context.get("my_firm") or {}):
                exclusions["incomplete_founder_observation"] += 1
                continue
            try:
                menu = compile_candidates(context, row["tick"], policy)
            except (ValueError, KeyError, TypeError):
                exclusions["context_cannot_compile"] += 1
                continue
            if menu.unsupported_reason:
                exclusions[menu.unsupported_reason] += 1
                continue
            if domain not in menu.metadata["domains"]:
                exclusions["no_represented_choice_for_domain"] += 1
                continue
            group = decision_hash({"source": source_hash, "actor": row["agent_id"]})
            record = {"contract": policy["version"], "compiler": menu.compiler_version,
                "agent_id": row["agent_id"], "tick": row["tick"], "purpose": row["purpose"],
                "observation_hash": menu.observation_hash, "menu_hash": menu.menu_hash,
                "question_hash": decision_hash(menu.evaluation["questions"]),
                "evaluation": menu.evaluation, "candidates": menu.candidates,
                "baseline_choice": menu.baseline_choice, "domain_metadata": menu.metadata,
                "id": decision_hash({"source": source_hash, "context": menu.observation_hash, "menu": menu.menu_hash}),
                "split": "calibration" if int(group[:8], 16) % 5 == 0 else "held_out", "label_choice": None,
                "counterfactual": True, "source_call_id": row["id"], "source_request_hash": decision_hash(request)}
            frozen_menu(record)
            stratum = "constrained" if menu.metadata["coverage_exclusions"] else (
                "pending_offer" if context.get("incoming_job_offers") or context.get("firm_job_offers") else "ordinary")
            record["stratum"] = stratum
            strata[stratum].append(record)
    finally:
        conn.close()
    if file_sha256(database) != source_hash:
        raise ValueError("source changed while preparing observations")
    eligible = sum(map(len, strata.values()))
    for records in strata.values():
        records.sort(key=lambda r: r["id"])
    selected = []
    # Stable round-robin sampling retains scarce contexts instead of allowing
    # a large ordinary stratum to silently dominate the first N records.
    while any(strata.values()) and len(selected) < limit:
        for key in sorted(strata):
            if strata[key] and len(selected) < limit:
                selected.append(strata[key].pop(0))
    value = {"protocol": PROTOCOL, "dataset_contract": "counterfactual-domain-context-v1",
        "source_sha256": source_hash, "source_seed": meta["seed"], "domain": domain,
        "compiler_policy": policy, "eligible_records": eligible, "exclusions": dict(exclusions),
        "records": selected, "limitations": ["Prospective menus; not decisions made in the source run",
            "No final-state joins or inferred missing resources", "No-choice and incomplete contexts remain exclusions",
            "Labels require independent adjudication", "A single world cannot establish generalization"]}
    publish_json(Path(output), {**value, "sha256": decision_hash(value)})
    return value
