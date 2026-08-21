"""Semantics 14 explicit attendance for due external-agent turns."""
from __future__ import annotations


NAME = "external_turn_attendance"

SQL = r"""
CREATE TABLE external_turn_attendance (
    id                  INTEGER PRIMARY KEY,
    connection_id       TEXT NOT NULL REFERENCES external_agent_connections(id),
    actor_id             INTEGER NOT NULL REFERENCES agents(id),
    target_tick          INTEGER NOT NULL CHECK(target_tick >= 0),
    turn_id              TEXT REFERENCES external_agent_turns(id),
    submission_id        TEXT REFERENCES external_action_submissions(id),
    attendance_status    TEXT NOT NULL
                         CHECK(attendance_status IN ('submitted','missed')),
    operational_reason   TEXT NOT NULL
                         CHECK(operational_reason IN
                           ('submitted','offline','deadline','dead_actor',
                            'revoked','no_submission')),
    decision_source      TEXT NOT NULL
                         CHECK(decision_source IN
                           ('external_submission','deterministic_fallback')),
    decision_policy      TEXT NOT NULL
                         CHECK(decision_policy IN
                           ('submitted_action_v1','safe_do_nothing_v1')),
    recorded_at          TEXT NOT NULL,
    UNIQUE(connection_id, target_tick),
    CHECK(
        (
            attendance_status='submitted'
            AND operational_reason='submitted'
            AND submission_id IS NOT NULL
            AND decision_source='external_submission'
            AND decision_policy='submitted_action_v1'
        )
        OR
        (
            attendance_status='missed'
            AND operational_reason<>'submitted'
            AND submission_id IS NULL
            AND decision_source='deterministic_fallback'
            AND decision_policy='safe_do_nothing_v1'
        )
    )
);
CREATE INDEX ix_external_turn_attendance_tick
    ON external_turn_attendance(target_tick, actor_id, connection_id);
CREATE INDEX ix_external_turn_attendance_status
    ON external_turn_attendance(attendance_status, operational_reason, target_tick);

CREATE TRIGGER external_turn_attendance_no_update
BEFORE UPDATE ON external_turn_attendance
BEGIN
    SELECT RAISE(ABORT, 'external turn attendance is immutable');
END;

CREATE TRIGGER external_turn_attendance_no_delete
BEFORE DELETE ON external_turn_attendance
BEGIN
    SELECT RAISE(ABORT, 'external turn attendance is immutable');
END;
"""


def verify(conn) -> None:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='external_turn_attendance'"
    ).fetchone()
    if table is None:
        raise RuntimeError("external_turn_attendance table is missing")
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='external_turn_attendance'"
        )
    }
    required_indexes = {
        "ix_external_turn_attendance_tick",
        "ix_external_turn_attendance_status",
    }
    if not required_indexes <= indexes:
        raise RuntimeError("external turn attendance indexes are missing")
    triggers = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='external_turn_attendance'"
        )
    }
    required_triggers = {
        "external_turn_attendance_no_update",
        "external_turn_attendance_no_delete",
    }
    if not required_triggers <= triggers:
        raise RuntimeError("external turn attendance immutability triggers are missing")
