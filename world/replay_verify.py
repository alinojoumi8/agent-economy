"""Canonical, table-by-table proof that a recorded run replayed exactly."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable
from collections.abc import Mapping

from engine.person_kind_history import PersonKindHistoryError, staff_promotion_identity
from world.replay_storage import (
    CallReferences, EventReferences, ReplayStorage, ReplayVerificationLimits,
    ReplayResourceLimitError,
)


# Metadata and checkpoint paths are operational, not simulated world state.
EXCLUDED_TABLES = {
    "run_meta", "checkpoints", "acceptance_checkpoints",
    "participant_control", "participant_actions",
    # External authentication, rate limiting, leases, and security telemetry are
    # wall-clock control-plane evidence. Executed submissions and their world
    # effects remain included in the exact deterministic comparison.
    "external_agent_credentials", "external_agent_turns",
    "external_oauth_clients", "external_oauth_codes",
    "external_rate_windows", "external_security_audit",
    # Provider concurrency/failure timing and host wall-clock timing are
    # operational evidence. Exact replay consumes llm_calls and intentionally
    # does not recreate live attempt telemetry.
    "llm_attempts", "runtime_tick_stats",
}
IGNORED_COLUMNS = {"created_at", "updated_at", "applied_at"}
TABLE_IGNORED_COLUMNS = {
    "external_action_submissions": {"completed_at", "source_submission_id"},
    "external_agent_connections": {"last_seen_at", "lease_expires_at"},
    # These are physical-order accelerators derived from source_id/target_id.
    # Canonical replay compares the referenced logical records instead.
    "causal_links": {"dedupe_key", "source_order_key", "target_order_key"},
}
LOGICAL_ROW_TABLES = {"beliefs", "llm_calls", "memories"}
SURROGATE_ID_COLUMNS = {
    **{table: {"id"} for table in LOGICAL_ROW_TABLES},
    # Operational participant events are intentionally filtered. Their rows
    # shift later event IDs without changing the deterministic event sequence.
    "events": {"id"},
}
IGNORED_EVENT_KINDS = {
    "report_generated", "report_failed",
    # Provider health events describe live control-plane interruptions. Exact
    # offline replay consumes stored responses and therefore cannot reproduce
    # them, while the resumed world's deterministic state remains unchanged.
    "provider_failure", "provider_pause",
    "participant_control_acquired", "participant_control_released",
    "participant_action_queued", "participant_action_replaced",
    "participant_action_executed", "participant_action_rejected", "participant_idle",
    # Non-terminal external receipts are wall-clock control-plane evidence.
    # The deterministic comparison retains external_action_executed and the
    # executed submission row that binds the action to its world effects.
    "external_action_queued", "external_action_stale", "external_action_rejected",
}
OPERATIONAL_LLM_PURPOSES = {"report_narrative"}
JSON_COLUMNS = {
    "participant_ids", "slant_tags", "source_event_ids",
}
LLM_REFERENCE_KEYS = {
    "llm_call_id", "model_call_id", "source_llm_call_id",
}
LLM_REFERENCE_JSON_COLUMNS = {
    ("events", "payload_json"),
}
EVENT_REFERENCE_JSON_COLUMNS = {
    ("news_articles", "source_event_ids"),
    ("claims", "source_event_ids_json"),
    ("information_items", "source_event_ids_json"),
    ("action_proposals", "evidence_event_ids_json"),
}
NESTED_EVENT_REFERENCE_JSON_COLUMNS = {
    ("events", "payload_json"),
    ("action_proposals", "payload_json"),
    ("action_proposals", "result_json"),
    ("causal_links", "provenance_json"),
}
EVENT_REFERENCE_COLUMNS = {
    ("person_residence_events", "event_id"),
    ("population_movements", "proposal_event_id"),
    ("population_movements", "outcome_event_id"),
    ("population_movement_assents", "event_id"),
    ("population_commitment_endings", "event_id"),
    ("population_scenario_manifest", "event_id"),
    ("population_scenario_receipts", "event_id"),
    ("legal_action_authorities", "event_id"),
    ("legal_action_authorities", "effect_event_id"),
    ("legal_counsel_requests", "authority_event_id"),
    ("legal_counsel_requests", "event_id"),
    ("legal_counsel_responses", "event_id"),
    ("legal_counsel_ends", "event_id"),
    ("firm_stewardships", "recorded_event_id"),
    ("legal_decision_authorities", "event_id"),
    ("estate_project_releases", "cancellation_event_id"),
    ("estate_property_bids", "event_id"),
    ("estate_property_bid_ends", "event_id"),
    ("estate_property_sales", "event_id"),
    ("estate_unlisted_bids", "event_id"),
    ("estate_unlisted_bid_ends", "event_id"),
    ("estate_unlisted_sales", "event_id"),
    ("estate_administrations", "event_id"),
    ("estate_administration_ends", "event_id"),
    ("liquidity_support_requests", "request_event_id"),
    ("service_cases", "created_event_id"),
    ("service_cases", "outcome_event_id"),
    ("service_appointments", "scheduled_event_id"),
    ("service_appointments", "outcome_event_id"),
    ("institution_tasks", "assigned_event_id"),
    ("institution_tasks", "outcome_event_id"),
    ("civic_authorizations", "issued_event_id"),
    ("civic_authorizations", "consumed_event_id"),
    ("attention_context_items", "source_event_id"),
    ("comm_messages", "created_event_id"),
    ("comm_messages", "publication_event_id"),
    ("comm_threads", "root_event_id"),
}
EVENT_REFERENCE_KEYS = {
    "authority_event_id", "effect_event_id",
    "request_event_id", "event_id", "created_event_id",
    "publication_event_id", "root_event_id",
}
EVENT_REFERENCE_LIST_KEYS = {"evidence_event_ids", "source_event_ids"}


ReferenceExpectationResolver = Callable[
    [str, dict[str, Any]], tuple[dict[str, Any], bool]]

SPECIALIZED_ACTION_PURPOSE_ROLES = {
    "central_banker", "credit_officer", "vc_partner", "lawyer",
}
INSTITUTIONAL_ACTION_PURPOSE_ROLES = {
    "exchange", "gov_official", "legislator_house", "legislator_senate",
    "regulator", "competition_regulator", "labor_regulator", "executive",
    "lobbyist", "permit_clerk",
}


def _connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    uri = f"file:{resolved.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        return conn
    except BaseException:
        conn.close()
        raise


HOUSEHOLD_DECISION_TABLES = {"household_decisions", "household_assents", "partnerships"}
DAILY_TIME_TABLES = {"time_plans", "time_days", "time_allocations", "child_care_days",
                     "wage_claims", "wage_claim_holders", "wage_accruals", "wage_settlements", "firm_labor_days"}
ESTATE_CASH_TABLES = {"cash_estates", "estate_cash_assets", "estate_loan_claims", "estate_cash_transfers"}
ASSET_SUCCESSION_TABLES = {"firm_stewardships", "estate_share_transfers", "estate_cases",
    "estate_beneficiaries", "estate_items", "estate_claims", "estate_claim_losses",
    "estate_receipts", "estate_cash_offsets", "estate_disbursements"}
ASSET_SUCCESSION_TABLES |= {"project_interest_lots", "project_stewardships"}
ASSET_SUCCESSION_TABLES |= {"estate_project_custody", "estate_project_releases"}
ASSET_SUCCESSION_TABLES |= {"estate_property_bids", "estate_property_bid_ends", "estate_property_sales"}
ASSET_SUCCESSION_TABLES |= {"estate_unlisted_bids", "estate_unlisted_bid_ends", "estate_unlisted_sales"}
ASSET_SUCCESSION_TABLES |= {"estate_administrations", "estate_administration_ends"}
ASSET_SUCCESSION_TABLES |= {"legal_decision_authorities"}
ASSET_SUCCESSION_TABLES |= {"legal_action_authorities", "legal_counsel_requests", "legal_counsel_responses", "legal_counsel_ends"}
ASSET_SUCCESSION_TABLES |= {"legal_awards", "legal_award_obligations", "legal_award_payments", "estate_claim_releases"}
ASSET_SUCCESSION_TABLES |= {"estate_legal_reserves", "estate_reserve_obligations", "estate_reserve_resolutions"}
ASSET_SUCCESSION_TABLES |= {"legal_wage_scopes", "legal_wage_awards", "wage_claim_novations", "legal_award_losses"}
ASSET_SUCCESSION_TABLES |= {"estate_security_lots", "estate_security_releases", "estate_security_orders",
                          "estate_security_sales", "estate_security_sale_lots"}
POPULATION_TABLES = {"person_residence_events", "population_resident_census",
                     "population_movements", "population_movement_assents",
                     "population_commitment_endings", "population_scenario_manifest",
                     "population_scenario_receipts"}
SEMANTIC_EXTENSIONS = ((17, 22, HOUSEHOLD_DECISION_TABLES), (18, 23, DAILY_TIME_TABLES),
                       (19, 24, ESTATE_CASH_TABLES), (20, 25, ASSET_SUCCESSION_TABLES),
                       (21, 26, POPULATION_TABLES))


def _engine_semantics(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT config_json FROM run_meta WHERE id=1").fetchone()
    config = json.loads(row[0]) if row else {}
    return int(config.get("engine_semantics_version", 1))


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    names = [str(row[0]) for row in rows if str(row[0]) not in EXCLUDED_TABLES]
    for semantics, _, tables in SEMANTIC_EXTENSIONS:
        if _engine_semantics(conn) >= semantics:
            continue
        # Only these declared empty extensions are compatible. Populated new
        # data and every older migration receipt remain part of comparison.
        names = [name for name in names if name not in tables
                 or conn.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone() is not None]
    return names


def _canonical_value(column: str, value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    text = str(value)
    if column.endswith("_json") or column in JSON_COLUMNS:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return text


def _logical_llm_call_references(
        conn: sqlite3.Connection, storage: ReplayStorage) -> Mapping[int, Any]:
    """Resolve deterministic call contents on demand within the read snapshot."""
    all_columns = [
        str(column[1]) for column in conn.execute('PRAGMA table_info("llm_calls")')]
    ignored = IGNORED_COLUMNS | SURROGATE_ID_COLUMNS["llm_calls"]
    identity_columns = [column for column in all_columns if column not in ignored]
    return CallReferences(conn, identity_columns, _canonical_value, storage)


def _future_staff_role(
        conn: sqlite3.Connection, agent_id: int, tick: int,
        current_kind: str) -> tuple[tuple[int, int, str] | None, bool]:
    """Read this actor's supported promotion without scanning the whole cohort."""
    promotions = conn.execute(
        "SELECT * FROM events WHERE kind='agency_staff_succeeded' AND subject_id=? "
        "AND tick>? ORDER BY tick,id", (agent_id, tick)).fetchall()
    if len(promotions) > 1:
        return None, False
    matched = set()
    predecessor = None
    for event in promotions:
        try:
            person, agency, region, place = staff_promotion_identity(event)
        except PersonKindHistoryError:
            return None, False
        assignments = conn.execute(
            "SELECT s.id FROM agency_staff s JOIN person_lifecycle p ON p.agent_id=s.agent_id "
            "WHERE s.agent_id=? AND s.agency_id=? AND s.region_id=? AND s.place_id=? "
            "AND s.role_key='permit_clerk' AND s.effective_tick=? AND s.created_tick=? "
            "AND p.origin_tick<=?",
            (person, agency, region, place, event['tick'], event['tick'], tick)).fetchall()
        if person != agent_id or current_kind != 'staff' or len(assignments) != 1:
            return None, False
        matched.add(assignments[0]['id'])
        # City._promote_successor requires a citizen with no personal role.
        predecessor = (event['tick'], event['id'], 'citizen')
    later_first = conn.execute(
        "SELECT s.id FROM agency_staff s JOIN person_lifecycle p ON p.agent_id=s.agent_id "
        "WHERE s.agent_id=? AND s.role_key='permit_clerk' AND s.effective_tick>? "
        "AND s.created_tick>p.origin_tick AND NOT EXISTS (SELECT 1 FROM agency_staff prior "
        "WHERE prior.agent_id=s.agent_id AND prior.created_tick<s.created_tick)",
        (agent_id, tick)).fetchall()
    if any(row['id'] not in matched for row in later_first):
        return None, False
    return predecessor, True


def _agent_role(
        conn: sqlite3.Connection, agent_id: int, *,
        tick: int | None = None) -> tuple[str | None, bool]:
    """Return the role used when the runtime creates an agent decision call."""
    row = conn.execute("SELECT role,kind FROM agents WHERE id=?", (int(agent_id),)).fetchone()
    if row is None:
        return None, False
    promotion = None
    if tick is not None and _engine_semantics(conn) >= 20:
        promotion, valid = _future_staff_role(conn, int(agent_id), int(tick), row['kind'])
        if not valid:
            return None, False
    if tick is not None and _engine_semantics(conn) >= 21:
        # Departure clears personal authority in NIGHT_CLOSE, before that
        # day's decisions. Its recorded snapshot still owns earlier calls;
        # return alone does not restore the released job.
        releases = conn.execute(
            "SELECT id,tick,phase,payload_json FROM events "
            "WHERE kind='population_authority_released' AND subject_type='agent' "
            "AND subject_id=? AND tick>? "
            "AND json_extract(payload_json,'$.binding_kind')='personal_role' "
            "ORDER BY tick,id", (int(agent_id), int(tick))).fetchall()
        if releases:
            release = releases[0]
            payload = json.loads(release['payload_json'])
            snapshot = payload.get('snapshot')
            movement_id = payload.get('movement_id')
            if (release['phase'] != 'NIGHT_CLOSE'
                    or payload.get('policy') != 'local_personal_authority_v1'
                    or type(payload.get('agent_id')) is not int or payload['agent_id'] != agent_id
                    or type(payload.get('source_id')) is not int or payload['source_id'] != agent_id
                    or type(movement_id) is not int or movement_id <= 0
                    or not isinstance(snapshot, dict)
                    or type(snapshot.get('id')) is not int or snapshot['id'] != agent_id
                    or (snapshot.get('role') is not None and not isinstance(snapshot['role'], str))
                    or (len(releases) > 1 and releases[1]['tick'] == release['tick'])):
                return None, False
            departure = conn.execute(
                "SELECT 1 FROM person_residence_events r JOIN population_movements m ON m.id=? "
                "WHERE r.agent_id=? AND r.tick=? AND r.state='outside' AND r.cause='departure' "
                "AND r.request_key=? AND m.status='applied' AND m.closed_tick=r.tick",
                (movement_id, int(agent_id), int(release['tick']), f'population:{movement_id}')).fetchone()
            if departure is None:
                return None, False
            if promotion is not None and promotion[:2] < (release['tick'], release['id']):
                return promotion[2], True
            return str(snapshot.get('role') or 'citizen'), True
    if promotion is not None:
        return promotion[2], True
    return str(row["role"] or "citizen"), True


def _institutional_role_purpose_mode(
        conn: sqlite3.Connection) -> bool | None:
    """Return the explicit routing marker, or None for historical profiles."""
    row = conn.execute("SELECT config_json FROM run_meta WHERE id=1").fetchone()
    if row is None:
        return None
    try:
        config = json.loads(str(row["config_json"] or "{}"))
    except (json.JSONDecodeError, TypeError):
        return None
    llm = config.get("llm", {}) if isinstance(config, dict) else {}
    if not isinstance(llm, dict) or "institutional_role_purposes" not in llm:
        return None
    return bool(llm["institutional_role_purposes"])


def _action_purposes_for(
        conn: sqlite3.Connection, agent_id: int, tick: int,
        role: str) -> frozenset[str]:
    """Reconstruct valid decision-call purposes without breaking old profiles."""
    if role in SPECIALIZED_ACTION_PURPOSE_ROLES:
        return frozenset({role})

    transition_tick = False
    if _engine_semantics(conn) >= 20:
        # A decision can precede a same-day sale or stewardship change. The
        # intervals record days, not phases, so both adjacent operators can
        # have a founder decision on that boundary day. Outside that day,
        # founding identity alone never extends a former operator's authority.
        intervals = conn.execute(
            "SELECT s.started_tick,s.ended_tick,f.bankrupt_tick FROM firms f "
            "LEFT JOIN firm_stewardships s ON s.firm_id=f.id AND s.started_tick<=? "
            "WHERE f.founded_tick<? AND (f.bankrupt_tick IS NULL OR f.bankrupt_tick>?) "
            "AND ((s.id IS NULL AND f.founder_agent_id=?) OR "
            "(s.steward_agent_id=? AND (s.ended_tick IS NULL OR s.ended_tick>=?)))",
            (tick, tick, tick, agent_id, agent_id, tick)).fetchall()
        founded_firm = bool(intervals)
        transition_tick = founded_firm and not any(
            (row["started_tick"] is None or row["started_tick"] < tick)
            and (row["ended_tick"] is None or row["ended_tick"] > tick)
            and (row["bankrupt_tick"] is None or row["bankrupt_tick"] > tick)
            for row in intervals)
    else:
        founded_firm = conn.execute(
            "SELECT 1 FROM firms WHERE founder_agent_id=? AND founded_tick<? "
            "AND (bankrupt_tick IS NULL OR bankrupt_tick>?) LIMIT 1",
            (int(agent_id), int(tick), int(tick))).fetchone() is not None
    mode = _institutional_role_purpose_mode(conn)
    if founded_firm and not transition_tick:
        # Markerless profiles predate explicit purpose routing, so accept their
        # historical generic decision identity as well as founder.
        return (frozenset({"founder"}) if mode is not None
                else frozenset({"founder", "decision"}))
    if mode is True and role in INSTITUTIONAL_ACTION_PURPOSE_ROLES:
        purposes = {role}
    elif mode is None and role != "citizen":
        # Stored pre-marker runs exist on both sides of the institutional-role
        # rollout. Preserve those exact replays while rejecting operational
        # purposes such as memory, newsroom, conversation, and reports.
        purposes = {"decision", role}
    else:
        purposes = {"decision"}
    if transition_tick:
        purposes.add("founder")
    return frozenset(purposes)


def _proposal_owner_for_result(
        conn: sqlite3.Connection, *, tick: int, action_type: str,
        result_key: str, result_id: int) -> tuple[sqlite3.Row | None, bool]:
    """Resolve a derived legal row to its one authoritative proposal."""
    matches: list[sqlite3.Row] = []
    for proposal in conn.execute(
            "SELECT actor_id,model_call_id,result_json FROM action_proposals "
            "WHERE tick=? AND action_type=? AND result_json IS NOT NULL",
            (int(tick), str(action_type))):
        try:
            result = json.loads(str(proposal["result_json"]))
        except (json.JSONDecodeError, TypeError):
            continue
        if (isinstance(result, dict)
                and not isinstance(result.get(result_key), bool)
                and result.get(result_key) == int(result_id)):
            matches.append(proposal)
    return (matches[0], True) if len(matches) == 1 else (None, False)


def _row_llm_expectations(
        conn: sqlite3.Connection, table: str,
        row: sqlite3.Row) -> tuple[dict[str, Any], bool]:
    """Derive the actor, turn, and role a persisted model pointer must own."""
    row_columns = set(row.keys())
    tick_column = ("tick" if "tick" in row_columns
                   else "created_tick" if "created_tick" in row_columns
                   else None)
    if tick_column is None:
        return {}, False
    expectations: dict[str, Any] = {"tick": int(row[tick_column])}
    owner_id: int | None = None
    context_valid = True

    if table == "action_proposals":
        owner_id = int(row["actor_id"])
    elif table == "agent_decisions":
        owner_id = int(row["agent_id"])
    elif table == "comm_messages":
        owner_id = int(row["sender_agent_id"])
    elif table == "causal_links" and row["actor_agent_id"] is not None:
        owner_id = int(row["actor_agent_id"])
    elif table == "legal_decisions":
        owner_id = int(row["decision_maker_id"])
        proposal, proposal_valid = _proposal_owner_for_result(
            conn, tick=int(row["tick"]), action_type="issue_legal_decision",
            result_key="decision_id", result_id=int(row["id"]))
        context_valid = context_valid and proposal_valid
        if proposal is not None:
            context_valid = context_valid and int(proposal["actor_id"]) == owner_id
            context_valid = context_valid and proposal["model_call_id"] == row["model_call_id"]
    elif table == "legal_filings":
        proposal, proposal_valid = _proposal_owner_for_result(
            conn, tick=int(row["tick"]), action_type="submit_filing",
            result_key="filing_id", result_id=int(row["id"]))
        context_valid = context_valid and proposal_valid
        if proposal is not None:
            owner_id = int(proposal["actor_id"])
            context_valid = context_valid and proposal["model_call_id"] == row["model_call_id"]

    if owner_id is None:
        return expectations, False
    expectations["agent_id"] = owner_id
    role, role_valid = _agent_role(conn, owner_id, tick=int(row[tick_column]))
    context_valid = context_valid and role_valid
    if role is not None:
        expectations["role"] = role
        expectations["purpose"] = _action_purposes_for(
            conn, owner_id, int(row[tick_column]), role)
        if table == "agent_decisions" and _engine_semantics(conn) >= 20:
            # Even on a stewardship boundary day, a pointer must refer to the
            # particular purpose recorded by this decision, not another valid
            # same-actor call from that day.
            context_valid = context_valid and row["purpose"] in expectations["purpose"]
            expectations["purpose"] = row["purpose"]
    return expectations, context_valid


def _event_llm_expectations(
        conn: sqlite3.Connection, event_row: sqlite3.Row,
        root: dict[str, Any], key: str,
        parent: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Derive provenance ownership for LLM references embedded in events."""
    expectations: dict[str, Any] = {"tick": int(event_row["tick"])}
    owner_id: int | None = None
    role: str | None = None
    purpose: str | None = None
    valid = True

    if (key == "model_call_id" and parent is root
            and str(event_row["kind"]) in {
                "workforce_recovery_model_action_replaced",
                "workforce_recovery_candidate_actions_coordinated"}):
        # These execution receipts describe changes to one recorded decision;
        # an arbitrary same-day model call is not sufficient provenance.
        owner_id = root.get("agent_id")
        call_id = root.get("model_call_id")
        if (isinstance(owner_id, bool) or not isinstance(owner_id, int)
                or not 0 < owner_id < 2**63
                or isinstance(call_id, bool) or not isinstance(call_id, int)
                or not 0 < call_id < 2**63 or event_row["phase"] != "EXECUTION"
                or event_row["subject_type"] != "agent"
                or event_row["subject_id"] != owner_id):
            return expectations, False
        if _engine_semantics(conn) >= 8:
            decisions = conn.execute(
                "SELECT * FROM agent_decisions WHERE tick=? AND agent_id=? "
                "AND model_call_id=?",
                (int(event_row["tick"]), owner_id, call_id),
            ).fetchmany(2)
            if len(decisions) != 1:
                return expectations, False
            expectations, valid = _row_llm_expectations(conn, "agent_decisions", decisions[0])
            allowed = expectations.get("purpose")
            purpose = str(decisions[0]["purpose"])
            valid = valid and (purpose in allowed if isinstance(allowed, (set, frozenset))
                               else purpose == allowed)
            expectations["purpose"] = purpose
            return expectations, valid
        # Semantics 7 emitted these receipts before agent_decisions existed.
        role, valid = _agent_role(conn, owner_id, tick=int(event_row["tick"]))
        expectations.update(agent_id=owner_id, role=role,
            purpose=_action_purposes_for(conn, owner_id, int(event_row["tick"]), role))
        return expectations, valid and _engine_semantics(conn) == 7

    if key == "source_llm_call_id" and "agent_id" in root:
        try:
            owner_id = int(root["agent_id"])
        except (TypeError, ValueError):
            valid = False
        source = str(root.get("source") or "")
        if source == "memory":
            role, purpose = "citizen", "memory"
        elif owner_id is not None:
            role, role_valid = _agent_role(conn, owner_id, tick=int(event_row['tick']))
            valid = valid and role_valid
            purpose = source or None
    elif key == "model_call_id" and "decision_actor_id" in root:
        try:
            owner_id = int(root["decision_actor_id"])
        except (TypeError, ValueError):
            valid = False
        role, purpose = "central_banker", "central_banker"
    elif key == "model_call_id" and parent.get("purpose") == "report_narrative":
        # Reports are operational and excluded from world-state equality, but
        # their retained local provenance still has a deterministic role.
        expectations["agent_id"] = None
        role, purpose = "reporter", "report_narrative"
    elif (key == "model_call_id"
          and str(event_row["kind"]) == "model_numeric_narrative_redacted"
          and "agent_id" in root):
        try:
            owner_id = int(root["agent_id"])
        except (TypeError, ValueError):
            valid = False
        if owner_id is not None:
            role, role_valid = _agent_role(conn, owner_id, tick=int(event_row['tick']))
            valid = valid and role_valid
        purpose = str(root.get("purpose") or "") or None
    else:
        valid = False

    if owner_id is not None:
        expectations["agent_id"] = owner_id
    if role is not None:
        expectations["role"] = role
    if purpose is not None:
        expectations["purpose"] = purpose
    return expectations, valid


def _logical_event_references(
        conn: sqlite3.Connection,
        llm_call_references: Mapping[int, Any],
        storage: ReplayStorage) -> Mapping[int, Any]:
    """Index event surrogate IDs by deterministic row contents."""
    references = EventReferences(storage)
    for row in conn.execute("SELECT * FROM events ORDER BY id"):
        storage.begin_record()
        payload = _canonical_value("payload_json", row["payload_json"])
        resolver = None
        if isinstance(payload, dict):
            resolver = lambda key, parent, *, _row=row, _root=payload: (
                _event_llm_expectations(conn, _row, _root, key, parent))
        payload, _valid = _canonicalize_nested_llm_references(
            payload, llm_call_references, resolver)
        # Provenance points backward to the request/evidence that authorized an
        # event, so an incremental index resolves the logical identity without
        # depending on this database's physical event IDs.
        payload, _valid = _canonicalize_nested_event_references(
            payload, references)
        references[int(row["id"])] = {"event": {
            "tick": int(row["tick"]),
            "kind": str(row["kind"]),
            "payload_json": payload,
            "phase": row["phase"],
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "importance": float(row["importance"]),
        }}
    return references


def _canonical_llm_reference(
        value: Any, llm_call_references: dict[int, Any],
        expectations: dict[str, Any] | None = None,
        context_valid: bool = True) -> tuple[Any, bool]:
    if value is None:
        return None, True
    # IDs are persisted as SQLite/JSON integers. Do not silently coerce bools,
    # numeric strings, fractional values, or non-finite floats into valid IDs.
    if isinstance(value, bool) or not isinstance(value, int):
        return {"invalid_llm_call_id": {
            "type": type(value).__name__,
            "value": str(value),
        }}, False
    key = value
    reference = llm_call_references.get(key)
    if reference is None:
        return {"dangling_llm_call_id": key}, False
    valid = bool(context_valid)
    call = reference.get("llm_call", {})
    for field, expected in (expectations or {}).items():
        actual = call.get(field)
        if isinstance(expected, (set, frozenset)):
            matches = actual in expected
        else:
            matches = actual == expected
        if not matches:
            valid = False
    return reference, valid


def _canonical_event_reference(
        value: Any, event_references: dict[int, Any]) -> tuple[Any, bool]:
    if isinstance(value, bool) or not isinstance(value, int):
        return {"invalid_event_id": {
            "type": type(value).__name__, "value": str(value),
        }}, False
    reference = event_references.get(value)
    if reference is None:
        return {"dangling_event_id": value}, False
    return reference, True


def _canonicalize_event_reference_list(
        value: Any, event_references: dict[int, Any]) -> tuple[Any, bool]:
    if not isinstance(value, list):
        return {"invalid_event_id_list": str(value)}, False
    canonical = []
    valid = True
    for event_id in value:
        resolved, item_valid = _canonical_event_reference(
            event_id, event_references)
        canonical.append(resolved)
        valid = valid and item_valid
    return canonical, valid


def _canonicalize_nested_event_references(
        value: Any, event_references: dict[int, Any]) -> tuple[Any, bool]:
    """Resolve event IDs embedded in persisted action/event provenance."""
    if isinstance(value, dict):
        canonical = {}
        references_valid = True
        for key, nested in value.items():
            # A canonical LLM reference contains the recorded request/response
            # verbatim. Replay copies that call record; do not reinterpret IDs
            # in its prompt as if they belonged to the local event table.
            if key == "llm_call":
                resolved, valid = nested, True
            elif key in EVENT_REFERENCE_KEYS:
                resolved, valid = _canonical_event_reference(
                    nested, event_references)
            elif key in EVENT_REFERENCE_LIST_KEYS:
                resolved, valid = _canonicalize_event_reference_list(
                    nested, event_references)
            else:
                resolved, valid = _canonicalize_nested_event_references(
                    nested, event_references)
            canonical[key] = resolved
            references_valid = references_valid and valid
        return canonical, references_valid
    if isinstance(value, list):
        canonical = []
        references_valid = True
        for nested in value:
            resolved, valid = _canonicalize_nested_event_references(
                nested, event_references)
            canonical.append(resolved)
            references_valid = references_valid and valid
        return canonical, references_valid
    return value, True


def _canonicalize_nested_llm_references(
        value: Any, llm_call_references: dict[int, Any],
        expectation_resolver: ReferenceExpectationResolver | None = None) -> tuple[Any, bool]:
    """Resolve local LLM IDs embedded in persisted JSON provenance."""
    if isinstance(value, dict):
        canonical = {}
        references_valid = True
        for key, nested in value.items():
            if key in LLM_REFERENCE_KEYS:
                expectations: dict[str, Any] = {}
                context_valid = True
                if expectation_resolver is not None:
                    expectations, context_valid = expectation_resolver(key, value)
                resolved, valid = _canonical_llm_reference(
                    nested, llm_call_references, expectations, context_valid)
            else:
                resolved, valid = _canonicalize_nested_llm_references(
                    nested, llm_call_references, expectation_resolver)
            canonical[key] = resolved
            references_valid = references_valid and valid
        return canonical, references_valid
    if isinstance(value, list):
        canonical = []
        references_valid = True
        for nested in value:
            resolved, valid = _canonicalize_nested_llm_references(
                nested, llm_call_references, expectation_resolver)
            canonical.append(resolved)
            references_valid = references_valid and valid
        return canonical, references_valid
    return value, True


def _table_digest(
        conn: sqlite3.Connection, table: str,
        llm_call_references: Mapping[int, Any],
        event_references: Mapping[int, Any], storage: ReplayStorage) -> tuple[int, str, bool]:
    all_columns = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
    ignored = (IGNORED_COLUMNS | SURROGATE_ID_COLUMNS.get(table, set())
               | TABLE_IGNORED_COLUMNS.get(table, set()))
    columns = [column for column in all_columns if column not in ignored]
    where = ""
    params: tuple[Any, ...] = ()
    if table == "events":
        placeholders = ",".join("?" for _ in IGNORED_EVENT_KINDS)
        where = f" WHERE kind NOT IN ({placeholders})"
        params = tuple(sorted(IGNORED_EVENT_KINDS))
    elif table == "llm_calls":
        placeholders = ",".join("?" for _ in OPERATIONAL_LLM_PURPOSES)
        where = f" WHERE purpose NOT IN ({placeholders})"
        params = tuple(sorted(OPERATIONAL_LLM_PURPOSES))
    elif table == "external_action_submissions":
        where = " WHERE status='executed'"
    elif table == "schema_migrations":
        # The additive migration receipt is not a historical simulated effect.
        # All pre-existing receipts and all Semantics-17 receipts remain exact.
        omitted = [str(version) for semantics, version, _ in SEMANTIC_EXTENSIONS if _engine_semantics(conn) < semantics]
        where = " WHERE version NOT IN (" + ",".join(omitted) + ")" if omitted else ""
    order = " ORDER BY id" if "id" in all_columns else ""
    selected = ",".join(f'"{column}"' for column in columns)
    rows = conn.execute(f'SELECT {selected} FROM "{table}"{where}{order}', params)
    count = 0
    digest = hashlib.sha256()
    logical = table in LOGICAL_ROW_TABLES
    if logical:
        storage.clear_sort()
    references_valid = True
    for row in rows:
        storage.begin_record()
        record = {}
        for column in columns:
            if column == "model_call_id":
                expectations: dict[str, Any] = {}
                context_valid = True
                if row[column] is not None:
                    expectations, context_valid = _row_llm_expectations(
                        conn, table, row)
                resolved, valid = _canonical_llm_reference(
                    row[column], llm_call_references,
                    expectations, context_valid)
                record[column] = resolved
                references_valid = references_valid and valid
            elif (table, column) in EVENT_REFERENCE_COLUMNS:
                if row[column] is None:
                    resolved, valid = None, True
                else:
                    resolved, valid = _canonical_event_reference(
                        row[column], event_references)
                record[column] = resolved
                references_valid = references_valid and valid
            elif (table == "causal_links"
                  and column in {"source_id", "target_id"}
                  and row[f"{column.removesuffix('_id')}_kind"] == "event"):
                try:
                    event_id: Any = int(row[column])
                except (TypeError, ValueError):
                    event_id = row[column]
                resolved, valid = _canonical_event_reference(
                    event_id, event_references)
                record[column] = resolved
                references_valid = references_valid and valid
            else:
                value = _canonical_value(column, row[column])
                if (table, column) in LLM_REFERENCE_JSON_COLUMNS:
                    resolver = None
                    if table == "events" and isinstance(value, dict):
                        resolver = lambda key, parent, *, _row=row, _root=value: (
                            _event_llm_expectations(
                                conn, _row, _root, key, parent))
                    value, valid = _canonicalize_nested_llm_references(
                        value, llm_call_references, resolver)
                    references_valid = references_valid and valid
                if (table, column) in EVENT_REFERENCE_JSON_COLUMNS:
                    value, valid = _canonicalize_event_reference_list(
                        value, event_references)
                    references_valid = references_valid and valid
                if (table, column) in NESTED_EVENT_REFERENCE_JSON_COLUMNS:
                    value, valid = _canonicalize_nested_event_references(
                        value, event_references)
                    references_valid = references_valid and valid
                record[column] = value
        encoded = storage.encode(record, exact=True)
        if logical:
            storage.add_sorted(encoded, count)
        else:
            digest.update(encoded)
            digest.update(b"\n")
        count += 1
    if logical:
        for encoded in storage.sorted_records():
            digest.update(encoded)
            digest.update(b"\n")
        storage.clear_sort()
    storage.check(force=True)
    return count, digest.hexdigest(), references_valid


def _connection_digests(
        database: sqlite3.Connection, names: list[str], storage: ReplayStorage) -> dict:
    storage.reset()
    with storage.read_limits(database):
        calls = _logical_llm_call_references(database, storage)
        events = _logical_event_references(database, calls, storage)
        return {name: _table_digest(database, name, calls, events, storage)
                for name in names}


def canonical_state_receipt(database: sqlite3.Connection, *,
                            excluded_protocol_tables: tuple[str, ...] = (),
                            limits: ReplayVerificationLimits | None = None,
                            scratch_dir: str | Path | None = None,
                            stats: dict | None = None) -> dict:
    """Hash deterministic state using the replay comparison's exact row rules.

    This is a state inventory, not evidence that a replay was executed. Paired
    genesis comparisons may exclude declared shock schedules and scenario
    descriptors; their separate digests remain in the receipt for inspection.
    """
    allowed = {"shocks", "scenario_packs"}
    if not set(excluded_protocol_tables) <= allowed:
        raise ValueError("only declared experiment protocol tables may be excluded")
    with ReplayStorage(limits=limits, scratch_dir=scratch_dir, stats=stats) as storage:
        with storage.read_limits(database):
            digests = _connection_digests(database, _tables(database), storage)
    aggregate = hashlib.sha256()
    tables, protocol_tables = {}, {}
    valid = True
    for name, (count, digest, references_valid) in digests.items():
        row = {"rows": count, "sha256": digest,
               "references_valid": references_valid}
        valid = valid and references_valid
        if name in excluded_protocol_tables:
            protocol_tables[name] = row
        else:
            tables[name] = row
            aggregate.update(f"{name}:{count}:{digest}\n".encode())
    return {"contract": "replay-canonical-state-v1", "sha256": aggregate.hexdigest(),
            "references_valid": valid, "tables": tables,
            "excluded_protocol_tables": protocol_tables}


def verify_replay(source_path: str | Path, replay_path: str | Path, *,
                  limits: ReplayVerificationLimits | None = None,
                  scratch_dir: str | Path | None = None,
                  stats: dict | None = None) -> dict:
    """Compare every deterministic table and return a machine-readable proof."""
    source = _connect(source_path)
    try:
        replay = _connect(replay_path)
        try:
            return verify_replay_connections(source, replay, limits=limits,
                                             scratch_dir=scratch_dir, stats=stats)
        finally:
            replay.close()
    finally:
        source.close()


def verify_replay_connections(
        source: sqlite3.Connection, replay: sqlite3.Connection, *,
        limits: ReplayVerificationLimits | None = None,
        scratch_dir: str | Path | None = None, stats: dict | None = None) -> dict:
    """Use the same proof rules with caller-owned, consistent read snapshots."""
    with ReplayStorage(limits=limits, scratch_dir=scratch_dir, stats=stats) as storage:
        with storage.read_limits(source), storage.read_limits(replay):
            source_tables = _tables(source)
            replay_tables = _tables(replay)
            names = sorted(set(source_tables) | set(replay_tables))
            results = []
            source_run = source.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
            replay_run = replay.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
            common = sorted(set(source_tables) & set(replay_tables))
            source_digests = _connection_digests(source, common, storage)
            replay_digests = _connection_digests(replay, common, storage)
            source_total = hashlib.sha256()
            replay_total = hashlib.sha256()
            for name in names:
                if name not in source_tables or name not in replay_tables:
                    results.append({
                        "table": name, "exact": False,
                        "source_rows": None if name not in source_tables else 0,
                        "replay_rows": None if name not in replay_tables else 0,
                        "source_hash": None, "replay_hash": None,
                    })
                    continue
                source_rows, source_hash, source_references_valid = source_digests[name]
                replay_rows, replay_hash, replay_references_valid = replay_digests[name]
                exact = (source_rows == replay_rows and source_hash == replay_hash
                         and source_references_valid and replay_references_valid)
                results.append({
                    "table": name, "exact": exact,
                    "source_rows": source_rows, "replay_rows": replay_rows,
                    "source_hash": source_hash, "replay_hash": replay_hash,
                })
                source_total.update(f"{name}:{source_rows}:{source_hash}\n".encode())
                replay_total.update(f"{name}:{replay_rows}:{replay_hash}\n".encode())

            ticks_exact = int(source_run["tick"]) == int(replay_run["tick"])
            return {
                "exact": ticks_exact and all(item["exact"] for item in results),
                "source_run_id": str(source_run["run_id"]),
                "replay_run_id": str(replay_run["run_id"]),
                "source_tick": int(source_run["tick"]),
                "replay_tick": int(replay_run["tick"]),
                "source_hash": source_total.hexdigest(),
                "replay_hash": replay_total.hexdigest(),
                "tables": results,
                "differences": [item["table"] for item in results if not item["exact"]]
                               + ([] if ticks_exact else ["run_meta.tick"]),
            }
