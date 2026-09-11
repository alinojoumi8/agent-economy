"""Draft immutable evidence for local commitments ended by departure."""

SQL = """
CREATE TABLE population_commitment_endings (
    id INTEGER PRIMARY KEY CHECK(id>0),
    movement_id INTEGER NOT NULL REFERENCES population_movements(id),
    agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    tick INTEGER NOT NULL CHECK(tick>0),
    kind TEXT NOT NULL CHECK(kind IN ('insurance','compute_access','loan_application','migration','stock_order','fx_order','ipo_bid','local_occupancy')),
    source_id INTEGER NOT NULL CHECK(source_id>0),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    UNIQUE(kind,source_id)
);
CREATE INDEX ix_population_commitment_movement ON population_commitment_endings(movement_id,agent_id,id);
CREATE TRIGGER population_commitment_binding BEFORE INSERT ON population_commitment_endings BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM population_movements m, json_each(m.terms_json,'$.member_ids') p
        WHERE m.id=NEW.movement_id AND m.status='pending' AND m.due_tick=NEW.tick
          AND json_extract(m.terms_json,'$.cause')='departure' AND p.value=NEW.agent_id
    ) THEN RAISE(ABORT,'commitment ending requires this pending departure') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM person_residence_events r WHERE r.agent_id=NEW.agent_id AND r.tick=NEW.tick
          AND r.cause='departure' AND r.request_key='population:'||NEW.movement_id AND r.event_id<NEW.event_id
    ) THEN RAISE(ABORT,'commitment ending requires recorded residence evidence') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.event_id AND e.tick=NEW.tick
          AND e.kind='population_commitment_ended' AND e.phase='NIGHT_CLOSE'
          AND e.subject_type='agent' AND e.subject_id=NEW.agent_id AND e.payload_json=NEW.evidence_json
          AND json_type(e.payload_json,'$.movement_id')='integer'
          AND json_type(e.payload_json,'$.agent_id')='integer'
          AND json_type(e.payload_json,'$.source_id')='integer'
          AND json_type(e.payload_json,'$.snapshot')='object'
          AND json_type(e.payload_json,'$.changes')='object'
          AND json_extract(e.payload_json,'$.movement_id')=NEW.movement_id
          AND json_extract(e.payload_json,'$.agent_id')=NEW.agent_id
          AND json_extract(e.payload_json,'$.kind')=NEW.kind
          AND json_extract(e.payload_json,'$.source_id')=NEW.source_id
          AND json_extract(e.payload_json,'$.policy')='end_local_commitments_retain_assets_v1'
          AND (SELECT COUNT(*) FROM json_each(e.payload_json))=7
    ) THEN RAISE(ABORT,'commitment ending lacks its matching event') END;
END;
CREATE TRIGGER population_commitment_immutable BEFORE UPDATE ON population_commitment_endings
BEGIN SELECT RAISE(ABORT,'commitment endings are immutable'); END;
CREATE TRIGGER population_commitment_no_delete BEFORE DELETE ON population_commitment_endings
BEGIN SELECT RAISE(ABORT,'commitment endings are permanent'); END;
"""

REQUIRED = {"population_commitment_endings", "ix_population_commitment_movement",
            "population_commitment_binding", "population_commitment_immutable", "population_commitment_no_delete"}
