"""Recorded mutual household decisions; no relationships inferred on upgrade."""

NAME = "household_decisions"
SQL = """
CREATE TABLE household_decisions (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    kind TEXT NOT NULL CHECK(kind IN ('partnership','joint_move','separation')),
    partner_id INTEGER REFERENCES agents(id),
    destination_region_id INTEGER REFERENCES regions(id),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    expires_tick INTEGER NOT NULL CHECK(expires_tick >= created_tick),
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','agreed','applied','rejected','expired','cancelled')),
    settled_tick INTEGER CHECK(settled_tick >= created_tick),
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE(actor_id,request_key),
    CHECK((kind='partnership' AND partner_id IS NOT NULL AND partner_id<>actor_id AND destination_region_id IS NULL)
       OR (kind='joint_move' AND partner_id IS NULL AND destination_region_id IS NOT NULL)
       OR (kind='separation' AND partner_id IS NULL AND destination_region_id IS NULL))
);
CREATE INDEX ix_household_decisions_status ON household_decisions(status,id);
CREATE TABLE household_assents (
    decision_id INTEGER NOT NULL REFERENCES household_decisions(id),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    decision TEXT NOT NULL CHECK(decision IN ('accept','reject')),
    tick INTEGER NOT NULL CHECK(tick >= 0),
    PRIMARY KEY(decision_id,actor_id)
);
CREATE TABLE partnerships (
    id INTEGER PRIMARY KEY,
    agent_a INTEGER NOT NULL REFERENCES agents(id),
    agent_b INTEGER NOT NULL REFERENCES agents(id),
    decision_id INTEGER NOT NULL UNIQUE REFERENCES household_decisions(id),
    started_tick INTEGER NOT NULL CHECK(started_tick >= 0),
    ended_tick INTEGER CHECK(ended_tick >= started_tick),
    end_reason TEXT,
    CHECK(agent_a < agent_b),
    CHECK((ended_tick IS NULL AND end_reason IS NULL) OR (ended_tick IS NOT NULL AND end_reason IS NOT NULL))
);
CREATE TRIGGER partnership_one_active_person BEFORE INSERT ON partnerships
WHEN NEW.ended_tick IS NULL AND EXISTS (
    SELECT 1 FROM partnerships WHERE ended_tick IS NULL
    AND (agent_a IN (NEW.agent_a,NEW.agent_b) OR agent_b IN (NEW.agent_a,NEW.agent_b)))
BEGIN SELECT RAISE(ABORT,'person already has an active partnership'); END;
CREATE TRIGGER partnership_identity_immutable BEFORE UPDATE OF agent_a,agent_b,decision_id,started_tick ON partnerships
BEGIN SELECT RAISE(ABORT,'partnership identity is immutable'); END;
CREATE TRIGGER partnership_no_reopen BEFORE UPDATE OF ended_tick ON partnerships
WHEN OLD.ended_tick IS NOT NULL
BEGIN SELECT RAISE(ABORT,'ended partnership is permanent'); END;
CREATE TRIGGER household_assent_immutable BEFORE UPDATE ON household_assents
BEGIN SELECT RAISE(ABORT,'household assent is immutable'); END;
CREATE TRIGGER household_assent_no_delete BEFORE DELETE ON household_assents
BEGIN SELECT RAISE(ABORT,'household assent is permanent'); END;
CREATE TRIGGER household_decision_terms_immutable
BEFORE UPDATE OF actor_id,request_key,kind,partner_id,destination_region_id,created_tick,expires_tick,snapshot_json ON household_decisions
BEGIN SELECT RAISE(ABORT,'household decision terms are immutable'); END;
"""


def verify(conn) -> None:
    objects = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}
    required = {"household_decisions", "household_assents", "partnerships",
                "ix_household_decisions_status", "partnership_one_active_person",
                "partnership_identity_immutable", "partnership_no_reopen",
                "household_assent_immutable", "household_assent_no_delete",
                "household_decision_terms_immutable"}
    if not required <= objects:
        raise RuntimeError("household decision tables or history guards are missing")
