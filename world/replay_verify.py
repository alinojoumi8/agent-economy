"""Canonical, table-by-table proof that a recorded run replayed exactly."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable


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
    "participant_control_acquired", "participant_control_released",
    "participant_action_queued", "participant_action_replaced",
    "participant_action_executed", "participant_action_rejected", "participant_idle",
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
    ("action_proposals", "evidence_event_ids_json"),
}
NESTED_EVENT_REFERENCE_JSON_COLUMNS = {
    ("events", "payload_json"),
    ("action_proposals", "payload_json"),
    ("action_proposals", "result_json"),
}
EVENT_REFERENCE_COLUMNS = {
    ("liquidity_support_requests", "request_event_id"),
}
EVENT_REFERENCE_KEYS = {"request_event_id", "event_id"}
EVENT_REFERENCE_LIST_KEYS = {"evidence_event_ids"}


ReferenceExpectationResolver = Callable[
    [str, dict[str, Any]], tuple[dict[str, Any], bool]]

SPECIALIZED_ACTION_PURPOSE_ROLES = {
    "central_banker", "credit_officer", "vc_partner", "lawyer",
}
INSTITUTIONAL_ACTION_PURPOSE_ROLES = {
    "exchange", "gov_official", "legislator_house", "legislator_senate",
    "regulator", "competition_regulator", "labor_regulator", "executive",
    "lobbyist",
}


def _connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    uri = f"file:{resolved.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if str(row[0]) not in EXCLUDED_TABLES]


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


def _logical_llm_call_references(conn: sqlite3.Connection) -> dict[int, Any]:
    """Index local surrogate IDs by their deterministic LLM call contents."""
    all_columns = [
        str(column[1]) for column in conn.execute('PRAGMA table_info("llm_calls")')]
    if not all_columns:
        return {}
    ignored = IGNORED_COLUMNS | SURROGATE_ID_COLUMNS["llm_calls"]
    identity_columns = [column for column in all_columns if column not in ignored]
    return {
        int(row["id"]): {"llm_call": {
            column: _canonical_value(column, row[column])
            for column in identity_columns
        }}
        for row in conn.execute("SELECT * FROM llm_calls")
    }


def _agent_role(conn: sqlite3.Connection, agent_id: int) -> tuple[str | None, bool]:
    """Return the role used when the runtime creates an agent decision call."""
    row = conn.execute("SELECT role FROM agents WHERE id=?", (int(agent_id),)).fetchone()
    if row is None:
        return None, False
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

    founded_firm = conn.execute(
        "SELECT 1 FROM firms WHERE founder_agent_id=? AND founded_tick<? "
        "AND (bankrupt_tick IS NULL OR bankrupt_tick>?) LIMIT 1",
        (int(agent_id), int(tick), int(tick))).fetchone() is not None
    mode = _institutional_role_purpose_mode(conn)
    if founded_firm:
        # Markerless profiles predate explicit purpose routing, so accept their
        # historical generic decision identity as well as founder.
        return (frozenset({"founder"}) if mode is not None
                else frozenset({"founder", "decision"}))
    if mode is True and role in INSTITUTIONAL_ACTION_PURPOSE_ROLES:
        return frozenset({role})
    if mode is None and role != "citizen":
        # Stored pre-marker runs exist on both sides of the institutional-role
        # rollout. Preserve those exact replays while rejecting operational
        # purposes such as memory, newsroom, conversation, and reports.
        return frozenset({"decision", role})
    return frozenset({"decision"})


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
    role, role_valid = _agent_role(conn, owner_id)
    context_valid = context_valid and role_valid
    if role is not None:
        expectations["role"] = role
        expectations["purpose"] = _action_purposes_for(
            conn, owner_id, int(row[tick_column]), role)
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

    if key == "source_llm_call_id" and "agent_id" in root:
        try:
            owner_id = int(root["agent_id"])
        except (TypeError, ValueError):
            valid = False
        source = str(root.get("source") or "")
        if source == "memory":
            role, purpose = "citizen", "memory"
        elif owner_id is not None:
            role, role_valid = _agent_role(conn, owner_id)
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
        llm_call_references: dict[int, Any]) -> dict[int, Any]:
    """Index event surrogate IDs by deterministic row contents."""
    references = {}
    for row in conn.execute("SELECT * FROM events ORDER BY id"):
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
        llm_call_references: dict[int, Any],
        event_references: dict[int, Any]) -> tuple[int, str, bool]:
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
    order = " ORDER BY id" if "id" in all_columns else ""
    selected = ",".join(f'"{column}"' for column in columns)
    rows = conn.execute(f'SELECT {selected} FROM "{table}"{where}{order}', params).fetchall()
    records = []
    references_valid = True
    for row in rows:
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
                resolved, valid = _canonical_event_reference(
                    row[column], event_references)
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
        records.append(json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8"))
    if table in LOGICAL_ROW_TABLES:
        records.sort()
    digest = hashlib.sha256()
    for record in records:
        digest.update(record)
        digest.update(b"\n")
    return len(rows), digest.hexdigest(), references_valid


def verify_replay(source_path: str | Path, replay_path: str | Path) -> dict:
    """Compare every deterministic table and return a machine-readable proof."""
    source = _connect(source_path)
    replay = _connect(replay_path)
    try:
        source_tables = _tables(source)
        replay_tables = _tables(replay)
        names = sorted(set(source_tables) | set(replay_tables))
        results = []
        source_run = source.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
        replay_run = replay.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
        source_llm_call_references = _logical_llm_call_references(source)
        replay_llm_call_references = _logical_llm_call_references(replay)
        source_event_references = _logical_event_references(
            source, source_llm_call_references)
        replay_event_references = _logical_event_references(
            replay, replay_llm_call_references)
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
            source_rows, source_hash, source_references_valid = _table_digest(
                source, name, source_llm_call_references, source_event_references)
            replay_rows, replay_hash, replay_references_valid = _table_digest(
                replay, name, replay_llm_call_references, replay_event_references)
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
    finally:
        source.close()
        replay.close()
