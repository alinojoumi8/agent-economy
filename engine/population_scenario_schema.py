"""Immutable declarations and command receipts for the draft population regime."""

SQL = """
CREATE INDEX ix_population_scenario_origin ON events(json_extract(payload_json,'$.random_key'),tick,subject_id)
    WHERE kind IN ('person_registered','birth') AND subject_type='agent';
CREATE TABLE population_scenario_manifest (
    id INTEGER PRIMARY KEY CHECK(id=1),
    schedule_json TEXT NOT NULL CHECK(json_valid(schedule_json) AND json_type(schedule_json)='array'),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TRIGGER population_scenario_declaration_binding BEFORE INSERT ON population_scenario_manifest BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.event_id AND e.tick=0 AND e.phase='GENESIS'
          AND e.kind='population_scenario_declared' AND e.subject_type='population_scenario' AND e.subject_id=1
          AND json_extract(e.payload_json,'$.version')=1
          AND json_extract(e.payload_json,'$.schedule')=json(NEW.schedule_json)
          AND (SELECT COUNT(*) FROM json_each(e.payload_json))=2
    ) THEN RAISE(ABORT,'population scenario lacks its declaration event') END;
END;
CREATE TRIGGER population_scenario_manifest_immutable BEFORE UPDATE ON population_scenario_manifest
BEGIN SELECT RAISE(ABORT,'population scenario is immutable'); END;
CREATE TRIGGER population_scenario_manifest_no_delete BEFORE DELETE ON population_scenario_manifest
BEGIN SELECT RAISE(ABORT,'population scenario is permanent'); END;

CREATE TABLE population_scenario_receipts (
    input_key TEXT PRIMARY KEY NOT NULL,
    tick INTEGER NOT NULL CHECK(tick>=0),
    outcome TEXT NOT NULL CHECK(outcome IN ('accepted','rejected')),
    reason TEXT NOT NULL,
    resolved_json TEXT NOT NULL CHECK(json_valid(resolved_json) AND json_type(resolved_json)='object'),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK((outcome='accepted' AND reason='' AND json_type(result_json)='object')
       OR (outcome='rejected' AND length(reason)>0 AND json_type(result_json)='null'))
);
CREATE TRIGGER population_scenario_receipt_binding BEFORE INSERT ON population_scenario_receipts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM population_scenario_manifest m, json_each(m.schedule_json) entry
        WHERE json_extract(entry.value,'$.key')=NEW.input_key
          AND json_extract(entry.value,'$.tick')=NEW.tick AND m.event_id<NEW.event_id
    ) THEN RAISE(ABORT,'population input was not declared for this day') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.event_id AND e.tick=NEW.tick
          AND e.phase=CASE WHEN NEW.tick=0 THEN 'GENESIS' ELSE 'NIGHT_CLOSE' END
          AND e.kind='population_scenario_input' AND e.subject_type='population_scenario' AND e.subject_id=1
          AND (SELECT COUNT(*) FROM json_each(e.payload_json))=5
          AND json_extract(e.payload_json,'$.input_key')=NEW.input_key
          AND json_extract(e.payload_json,'$.outcome')=NEW.outcome
          AND json_extract(e.payload_json,'$.reason')=NEW.reason
          AND json_extract(e.payload_json,'$.resolved')=json(NEW.resolved_json)
          AND json_quote(json_extract(e.payload_json,'$.result'))=json(NEW.result_json)
    ) THEN RAISE(ABORT,'population input lacks its outcome event') END;
END;
CREATE TRIGGER population_scenario_receipts_immutable BEFORE UPDATE ON population_scenario_receipts
BEGIN SELECT RAISE(ABORT,'population input outcomes are immutable'); END;
CREATE TRIGGER population_scenario_receipts_no_delete BEFORE DELETE ON population_scenario_receipts
BEGIN SELECT RAISE(ABORT,'population input outcomes are permanent'); END;
"""

REQUIRED = {
    'ix_population_scenario_origin',
    'population_scenario_manifest', 'population_scenario_declaration_binding',
    'population_scenario_manifest_immutable', 'population_scenario_manifest_no_delete',
    'population_scenario_receipts', 'population_scenario_receipt_binding',
    'population_scenario_receipts_immutable', 'population_scenario_receipts_no_delete',
}
