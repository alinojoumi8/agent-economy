"""Draft movement agreements, installed by the unregistered residence migration."""

SQL = """
CREATE TABLE population_movements (
    id INTEGER PRIMARY KEY CHECK(id>0),
    actor_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    household_id INTEGER NOT NULL REFERENCES households(id),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    created_tick INTEGER NOT NULL CHECK(created_tick>=0),
    due_tick INTEGER NOT NULL CHECK(due_tick>created_tick),
    terms_json TEXT NOT NULL CHECK(json_valid(terms_json)),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    proposal_event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','applied','cancelled')),
    closed_tick INTEGER,
    reason TEXT,
    destination_household_id INTEGER REFERENCES households(id),
    outcome_event_id INTEGER UNIQUE REFERENCES events(id),
    UNIQUE(actor_id,request_key),
    CHECK((status='pending' AND closed_tick IS NULL AND reason IS NULL
           AND destination_household_id IS NULL AND outcome_event_id IS NULL)
       OR (status='applied' AND closed_tick=due_tick AND reason='applied'
           AND destination_household_id IS NOT NULL AND outcome_event_id IS NOT NULL)
       OR (status='cancelled' AND closed_tick>=created_tick AND length(reason)>0
           AND destination_household_id IS NULL AND outcome_event_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_population_pending_household ON population_movements(household_id) WHERE status='pending';
CREATE INDEX ix_population_due ON population_movements(status,due_tick,id);
CREATE TRIGGER population_proposal_binding BEFORE INSERT ON population_movements BEGIN
    SELECT CASE WHEN NEW.status<>'pending' OR NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.proposal_event_id AND e.tick=NEW.created_tick
          AND e.kind='population_movement_proposed' AND e.subject_type='agent' AND e.subject_id=NEW.actor_id
          AND json_extract(e.payload_json,'$.terms')=json(NEW.terms_json)
          AND json_extract(e.payload_json,'$.snapshot')=json(NEW.snapshot_json)
          AND json_extract(e.payload_json,'$.request_key')=NEW.request_key
          AND json_extract(e.payload_json,'$.due_tick')=NEW.due_tick
          AND json_extract(NEW.snapshot_json,'$.household_id')=NEW.household_id
    ) THEN RAISE(ABORT,'movement proposal lacks bound terms and snapshot') END;
END;
CREATE TRIGGER population_movement_close BEFORE UPDATE ON population_movements BEGIN
    SELECT CASE WHEN OLD.status<>'pending' OR NEW.status='pending'
        OR NEW.id IS NOT OLD.id OR NEW.actor_id IS NOT OLD.actor_id
        OR NEW.household_id IS NOT OLD.household_id OR NEW.request_key IS NOT OLD.request_key
        OR NEW.created_tick IS NOT OLD.created_tick OR NEW.due_tick IS NOT OLD.due_tick
        OR NEW.terms_json IS NOT OLD.terms_json OR NEW.snapshot_json IS NOT OLD.snapshot_json
        OR NEW.proposal_event_id IS NOT OLD.proposal_event_id
        THEN RAISE(ABORT,'movement terms and terminal outcomes are immutable') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.outcome_event_id AND e.tick=NEW.closed_tick
          AND e.kind='population_movement_closed' AND e.subject_type='agent' AND e.subject_id=NEW.actor_id
          AND json_extract(e.payload_json,'$.movement_id')=NEW.id
          AND json_extract(e.payload_json,'$.status')=NEW.status
          AND json_extract(e.payload_json,'$.reason')=NEW.reason
          AND json_extract(e.payload_json,'$.destination_household_id') IS NEW.destination_household_id
    ) THEN RAISE(ABORT,'movement outcome lacks its event') END;
END;
CREATE TRIGGER population_movement_no_delete BEFORE DELETE ON population_movements
BEGIN SELECT RAISE(ABORT,'movement agreements are permanent'); END;

CREATE TABLE population_movement_assents (
    id INTEGER PRIMARY KEY CHECK(id>0),
    movement_id INTEGER NOT NULL REFERENCES population_movements(id),
    actor_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    decision TEXT NOT NULL CHECK(decision IN ('accept','decline','withdraw')),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    UNIQUE(movement_id,actor_id,decision)
);
CREATE TRIGGER population_assent_binding BEFORE INSERT ON population_movement_assents BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM population_movements m, json_each(m.snapshot_json,'$.adult_ids') a
        WHERE m.id=NEW.movement_id AND m.status='pending' AND a.value=NEW.actor_id
          AND NEW.tick BETWEEN m.created_tick AND m.due_tick
    ) THEN RAISE(ABORT,'movement assent requires a pending affected adult') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.event_id AND e.tick=NEW.tick
          AND e.kind='population_movement_assent' AND e.subject_type='agent' AND e.subject_id=NEW.actor_id
          AND json_extract(e.payload_json,'$.movement_id')=NEW.movement_id
          AND json_extract(e.payload_json,'$.decision')=NEW.decision
    ) THEN RAISE(ABORT,'movement assent lacks its event') END;
END;
CREATE TRIGGER population_assent_immutable BEFORE UPDATE ON population_movement_assents
BEGIN SELECT RAISE(ABORT,'movement assent is immutable'); END;
CREATE TRIGGER population_assent_no_delete BEFORE DELETE ON population_movement_assents
BEGIN SELECT RAISE(ABORT,'movement assent is permanent'); END;
"""

REQUIRED = {
    "population_movements", "ix_population_pending_household", "ix_population_due",
    "population_proposal_binding", "population_movement_close", "population_movement_no_delete",
    "population_movement_assents", "population_assent_binding", "population_assent_immutable",
    "population_assent_no_delete",
}
