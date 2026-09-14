"""Read-only population boundaries for the draft open-world observer.

Being a known, living financial owner does not establish local residence.
Never infer an outside location from a retained wallet, title or household.
"""
from collections import defaultdict
import json
import sqlite3

from engine.population import read_movement
from engine.population_history import ResidenceError, ResidenceHistory
from engine.population_statistics import residence_cohorts_at
from engine.position_history import account_balances_at

from .envelope import ProjectionRequestError, semantics_version


class PopulationProjectionError(ProjectionRequestError):
    def __init__(self):
        super().__init__('Population history is unavailable at the selected day.')


def population_at(store, tick: int) -> dict[int, dict] | None:
    """None preserves the pre-21 projection contract; an empty dict is valid."""
    if semantics_version(store) < 21:
        return None
    try:
        cohorts = residence_cohorts_at(store, tick)
        history = ResidenceHistory(store)
        # Include predecessors, not just the final row's immediate binding.
        # Restrict the chain walk to the selected boundary so later origins are
        # never exposed or required to inspect a valid prior population.
        prior = {}
        for row in store.query('SELECT * FROM person_residence_events WHERE tick<=? ORDER BY event_id', (tick,)):
            previous = prior.get(row['agent_id'])
            if row['previous_id'] != (previous['id'] if previous is not None else None):
                raise ResidenceError('selected residence chain skips a predecessor')
            prior[row['agent_id']] = history._validate_record(row, previous=previous)
        result = {}
        for state, people in cohorts.items():
            for person in people:
                aid = person['agent_id']
                record = prior[aid]
                result[aid] = dict(state=state, since_tick=record['tick'],
                    source='recorded_population_residence',
                    evidence_ref=dict(kind='event', id=record['event_id'], tick=record['tick']))
        return result
    except (ResidenceError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise PopulationProjectionError() from exc


def population_counts(population: dict[int, dict] | None) -> dict:
    if population is None:
        return {}
    residents = sum(item['state'] == 'resident' for item in population.values())
    return dict(known_living_population=len(population), resident_population=residents,
                known_living_outside=len(population) - residents)


def local_ids(population: dict[int, dict]) -> set[int]:
    return {aid for aid, item in population.items() if item['state'] == 'resident'}


def resident_regions_at(store, agents: list[dict], tick: int, population: dict[int, dict]) -> dict:
    """Merge internal moves and external returns using their recorded order.

    The first later move's origin reconstructs a prior region when current
    agents.region_id has changed. Future facts are used only to undo that cache;
    neither their destination nor their event references enter the projection.
    """
    try:
        ids = {int(agent['id']) for agent in agents}
        moves = defaultdict(list)
        migration_events = defaultdict(list)
        for event in store.query("SELECT * FROM events WHERE kind='agent_migrated' ORDER BY id"):
            if event['subject_id'] in ids:
                payload = json.loads(event['payload_json'])
                migration_events[payload['migration_id']].append((event, payload))
        for move in store.query("SELECT * FROM migrations WHERE status='completed' ORDER BY id"):
            aid = move['agent_id']
            if aid not in ids:
                continue
            evidence = migration_events[move['id']]
            if len(evidence) != 1:
                raise ResidenceError('migration evidence is missing or ambiguous')
            event, payload = evidence[0]
            if (event['subject_type'] != 'agent' or event['subject_id'] != aid
                    or event['tick'] != move['completed_tick'] or event['phase'] != 'NIGHT_CLOSE'
                    or payload['origin_region_id'] != move['origin_region_id']
                    or payload['destination_region_id'] != move['destination_region_id']):
                raise ResidenceError('migration source disagrees with its evidence')
            moves[aid].append((move['completed_tick'], event['id'],
                               move['origin_region_id'], move['destination_region_id']))
        for candidate in store.query("SELECT id FROM population_movements WHERE status='applied' ORDER BY id"):
            movement = read_movement(store, candidate['id'])
            terms = json.loads(movement['terms_json'])
            if terms['cause'] != 'return':
                continue
            snapshot = json.loads(movement['snapshot_json'])
            for aid in terms['member_ids']:
                if aid in ids:
                    moves[aid].append((movement['closed_tick'], movement['outcome_event_id'],
                                       snapshot['region_id'], terms['destination_region_id']))
        current = {row['id']: row['region_id'] for row in store.query('SELECT id,region_id FROM agents')}
        result = {}
        for aid in ids:
            if population[aid]['state'] != 'resident':
                result[aid] = None
                continue
            transitions = sorted(moves[aid])
            for previous, following in zip(transitions, transitions[1:]):
                if previous[3] != following[2] or previous[1] >= following[1]:
                    raise ResidenceError('regional move history is inconsistent')
            if transitions and transitions[-1][3] != current[aid]:
                raise ResidenceError('current regional cache disagrees with history')
            prior = [move for move in transitions if move[0] <= tick]
            result[aid] = prior[-1][3] if prior else transitions[0][2] if transitions else current[aid]
        return result
    except (ResidenceError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise PopulationProjectionError() from exc


def cash_by_person_at(store, tick: int) -> dict[int, dict[str, int]]:
    """Keep currencies separate and include retained historical cash wallets."""
    cash = defaultdict(lambda: defaultdict(int))
    for account in account_balances_at(store, tick):
        if account['owner_type'] == 'agent' and account['kind'] in {'checking', 'savings', 'fx'}:
            cash[account['owner_id']][account['currency_code']] += int(account['amount_cents'])
    return {aid: dict(sorted(amounts.items())) for aid, amounts in cash.items()}


def resident_presence_at(store, tick: int, population: dict[int, dict]) -> list[dict]:
    """Filter local presence before anonymizing licensing-office occupancy."""
    allowed = local_ids(population)
    visible, offices = [], {}
    for row in store.query(
            'SELECT ep.tick,ep.slot,ep.agent_id,a.name,a.role,a.occupation,'
            'ep.place_id,p.name AS place_name,p.kind AS place_kind,p.x,p.y,ep.source_type,ep.priority '
            'FROM effective_presence ep JOIN agents a ON a.id=ep.agent_id '
            'JOIN places p ON p.id=ep.place_id WHERE ep.tick=? ORDER BY ep.slot,ep.place_id,ep.agent_id', (tick,)):
        if row['agent_id'] not in allowed:
            continue
        item = dict(row)
        if item['place_kind'] != 'licensing_office':
            visible.append(item)
            continue
        key = item['slot'], item['place_id']
        if key not in offices:
            item.update(agent_id=None, name=None, role=None, occupation=None,
                        source_type='privacy_aggregate', priority=None, occupancy=0)
            offices[key] = item
        offices[key]['occupancy'] += 1
    return [*visible, *offices.values()]
