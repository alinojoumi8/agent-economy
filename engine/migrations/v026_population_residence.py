"""Draft residence history; register only with the completed population boundary."""

from ..population_movement_schema import SQL as MOVEMENT_SQL, REQUIRED as MOVEMENT_REQUIRED
from ..population_commitment_schema import SQL as COMMITMENT_SQL, REQUIRED as COMMITMENT_REQUIRED
from ..population_scenario_schema import SQL as SCENARIO_SQL, REQUIRED as SCENARIO_REQUIRED

NAME = "population_residence_history"

SQL = """
CREATE TABLE person_residence_events (
    id INTEGER PRIMARY KEY CHECK(id>0),
    agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    state TEXT NOT NULL CHECK(state IN ('resident','outside')),
    cause TEXT NOT NULL CHECK(cause IN ('genesis','birth','arrival','engine_created','departure','return')),
    previous_id INTEGER UNIQUE REFERENCES person_residence_events(id),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    ledger_frontier INTEGER NOT NULL CHECK(ledger_frontier>=0),
    accounting_policy TEXT NOT NULL CHECK(accounting_policy='retained_assets_no_transfer_v1'),
    UNIQUE(agent_id,request_key),
    CHECK((cause IN ('genesis','birth','arrival','engine_created') AND previous_id IS NULL AND state='resident')
       OR (cause='departure' AND previous_id IS NOT NULL AND state='outside' AND tick>0)
       OR (cause='return' AND previous_id IS NOT NULL AND state='resident' AND tick>0))
);
CREATE UNIQUE INDEX ix_person_residence_origin ON person_residence_events(agent_id) WHERE previous_id IS NULL;
CREATE INDEX ix_person_residence_history ON person_residence_events(agent_id,tick,event_id);
CREATE INDEX ix_person_residence_current ON person_residence_events(agent_id,event_id);
CREATE INDEX ix_person_residence_tick ON person_residence_events(tick,cause,agent_id);
CREATE TRIGGER person_residence_chain BEFORE INSERT ON person_residence_events
BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM population_resident_census WHERE tick>=NEW.tick)
        THEN RAISE(ABORT,'residence would rewrite a recorded census') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM person_lifecycle p JOIN agents a ON a.id=p.agent_id
        WHERE p.agent_id=NEW.agent_id AND p.origin_tick<=NEW.tick AND a.alive=1 AND p.death_tick IS NULL
    ) THEN RAISE(ABORT,'residence requires a registered living person') END;
    SELECT CASE WHEN NEW.previous_id IS NOT (
        SELECT id FROM person_residence_events WHERE agent_id=NEW.agent_id ORDER BY event_id DESC LIMIT 1
    ) THEN RAISE(ABORT,'residence predecessor is not current') END;
    SELECT CASE WHEN NEW.previous_id IS NULL AND NOT EXISTS (
        SELECT 1 FROM person_lifecycle WHERE agent_id=NEW.agent_id AND origin=NEW.cause AND origin_tick=NEW.tick
    ) THEN RAISE(ABORT,'residence origin disagrees with person identity') END;
    SELECT CASE WHEN NEW.previous_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM person_residence_events p WHERE p.id=NEW.previous_id AND p.agent_id=NEW.agent_id
          AND p.tick<=NEW.tick AND p.event_id<NEW.event_id AND p.state<>NEW.state
    ) THEN RAISE(ABORT,'residence transition is not chronological and alternating') END;
    SELECT CASE WHEN NEW.ledger_frontier<>(SELECT COALESCE(MAX(id),0) FROM transactions)
        THEN RAISE(ABORT,'residence ledger frontier is not current') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e WHERE e.id=NEW.event_id AND e.tick=NEW.tick
          AND e.kind='population_residence_recorded' AND e.subject_type='agent' AND e.subject_id=NEW.agent_id
          AND e.phase=CASE WHEN NEW.cause='genesis' THEN 'GENESIS' ELSE 'NIGHT_CLOSE' END
          AND (SELECT COUNT(*) FROM json_each(e.payload_json))=6
          AND json_type(e.payload_json,'$.previous_id') IN ('integer','null')
          AND json_type(e.payload_json,'$.ledger_frontier')='integer'
          AND json_extract(e.payload_json,'$.state')=NEW.state
          AND json_extract(e.payload_json,'$.cause')=NEW.cause
          AND json_extract(e.payload_json,'$.previous_id') IS NEW.previous_id
          AND json_extract(e.payload_json,'$.request_key')=NEW.request_key
          AND json_extract(e.payload_json,'$.ledger_frontier')=NEW.ledger_frontier
          AND json_extract(e.payload_json,'$.accounting_policy')=NEW.accounting_policy
    ) THEN RAISE(ABORT,'residence event does not bind the recorded transition') END;
END;
CREATE TRIGGER person_residence_immutable BEFORE UPDATE ON person_residence_events
BEGIN SELECT RAISE(ABORT,'residence history is immutable'); END;
CREATE TRIGGER person_residence_no_delete BEFORE DELETE ON person_residence_events
BEGIN SELECT RAISE(ABORT,'residence history is permanent'); END;

CREATE TABLE population_resident_census (
    tick INTEGER PRIMARY KEY CHECK(tick>=0),
    opening_residents INTEGER NOT NULL CHECK(opening_residents>=0),
    births INTEGER NOT NULL CHECK(births>=0),
    arrivals INTEGER NOT NULL CHECK(arrivals>=0),
    returns INTEGER NOT NULL CHECK(returns>=0),
    other_entries INTEGER NOT NULL CHECK(other_entries>=0),
    departures INTEGER NOT NULL CHECK(departures>=0),
    resident_deaths INTEGER NOT NULL CHECK(resident_deaths>=0),
    closing_residents INTEGER NOT NULL CHECK(closing_residents>=0),
    known_living_outside INTEGER NOT NULL CHECK(known_living_outside>=0),
    total_known_living INTEGER NOT NULL CHECK(total_known_living>=0),
    CHECK(closing_residents=opening_residents+births+arrivals+returns+other_entries-departures-resident_deaths),
    CHECK(total_known_living=closing_residents+known_living_outside)
);
CREATE TRIGGER resident_census_immutable BEFORE UPDATE ON population_resident_census
BEGIN SELECT RAISE(ABORT,'resident census is immutable'); END;
CREATE TRIGGER resident_census_no_delete BEFORE DELETE ON population_resident_census
BEGIN SELECT RAISE(ABORT,'resident census is permanent'); END;
"""


SQL += MOVEMENT_SQL
SQL += COMMITMENT_SQL
SQL += SCENARIO_SQL


def verify(conn):
    required = {
        "person_residence_events", "ix_person_residence_origin", "ix_person_residence_history",
        "ix_person_residence_tick", "ix_person_residence_current", "person_residence_chain", "person_residence_immutable",
        "person_residence_no_delete", "population_resident_census", "resident_census_immutable",
        "resident_census_no_delete",
    }
    present = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}
    if not (required | MOVEMENT_REQUIRED | COMMITMENT_REQUIRED | SCENARIO_REQUIRED) <= present:
        raise RuntimeError("population residence history or guards are missing")
