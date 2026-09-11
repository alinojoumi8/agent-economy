"""Prospective, origin-bound movement inputs for Semantics 21.

These are declared experimental inputs. They never impersonate endogenous
agent decisions or manufacture the assent of another household member.
"""
from __future__ import annotations

import json
import re

from .keyed_random import person_key
from .population import MovementError, _json
from .population_history import ResidenceError, _integer


def _key(value, name='key'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}', value):
        raise ResidenceError(f'{name} must be a stable 1 to 64 character identifier')
    return value


def _origin(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.isprintable():
        raise ResidenceError('person references must be recorded origin keys')
    return value


def parse_schedule(config, semantics):
    """Validate the complete schedule before any World construction effects."""
    population = config.get('population') or {}
    if not isinstance(population, dict):
        raise ResidenceError('population configuration must be an object')
    raw = population.get('movement_schedule', [])
    if not isinstance(raw, list) or len(raw) > 1024:
        raise ResidenceError('movement_schedule must list at most 1024 inputs')
    if raw and semantics < 21:
        raise ResidenceError('population scenarios require Semantics 21')
    if raw and (config.get('lifecycle') or {}).get('population_mode', 'stable') != 'drift':
        raise ResidenceError('population scenarios require the drift base without automatic replacement')
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise ResidenceError('each population input must be an object')
        required = {'key', 'tick', 'action', 'actor'}
        if item.get('action') == 'propose':
            required |= {'cause', 'members', 'due_tick'}
            optional = {'care_plan', 'destination_region_id'}
        elif item.get('action') == 'respond':
            required |= {'proposal', 'decision'}
            optional = set()
        else:
            raise ResidenceError('population input action must be propose or respond')
        if not required <= item.keys() or item.keys() - required - optional:
            raise ResidenceError('population input has missing or unknown fields')
        entry = {'key': _key(item['key']), 'tick': _integer(item['tick'], 'tick'),
                 'action': item['action'], 'actor': _origin(item['actor'])}
        if entry['action'] == 'propose':
            due = _integer(item['due_tick'], 'due_tick', minimum=1)
            members = item['members']
            if not isinstance(members, list) or not 1 <= len(members) <= 128:
                raise ResidenceError('members must list 1 to 128 recorded origins')
            members = sorted(_origin(person) for person in members)
            if len(set(members)) != len(members) or entry['actor'] not in members:
                raise ResidenceError('moving members must be unique and include the actor')
            if due <= entry['tick'] or not isinstance(item['cause'], str) or item['cause'] not in {'departure', 'return'}:
                raise ResidenceError('movement must be prospective with a supported cause')
            region = item.get('destination_region_id')
            if item['cause'] == 'return':
                _integer(region, 'destination_region_id', minimum=1)
            elif region is not None:
                raise ResidenceError('departure has no modeled destination region')
            care = item.get('care_plan', [])
            if not isinstance(care, list) or len(care) > 128:
                raise ResidenceError('care_plan must list at most 128 child dispositions')
            normalized = []
            for disposition in care:
                if not isinstance(disposition, dict) or set(disposition) != {'child', 'guardian'}:
                    raise ResidenceError('care disposition needs child and guardian origin keys')
                normalized.append({key: _origin(disposition[key]) for key in ('child', 'guardian')})
            normalized.sort(key=lambda value: value['child'])
            if len({value['child'] for value in normalized}) != len(normalized):
                raise ResidenceError('duplicate child care disposition')
            entry.update(cause=item['cause'], members=members, due_tick=due,
                         destination_region_id=region, care_plan=normalized)
        else:
            if not isinstance(item['decision'], str) or item['decision'] not in {'accept', 'decline', 'withdraw'}:
                raise ResidenceError('unsupported population response')
            entry.update(proposal=_key(item['proposal'], 'proposal'), decision=item['decision'])
        entries.append(entry)
    by_key = {entry['key']: entry for entry in entries}
    if len(by_key) != len(entries):
        raise ResidenceError('duplicate population input key')
    for entry in entries:
        if entry['action'] == 'respond':
            proposal = by_key.get(entry['proposal'])
            if (not proposal or proposal['action'] != 'propose'
                    or not proposal['tick'] <= entry['tick'] <= proposal['due_tick']):
                raise ResidenceError('response must name a declared proposal within its pending days')
    return sorted(entries, key=lambda value: (value['tick'], value['action'] != 'propose', value['key']))


class PopulationScenario:
    def __init__(self, economy, schedule):
        self.e, self.store = economy, economy.store
        self.schedule = json.loads(_json(schedule))
        self.inputs = {entry['key']: entry for entry in self.schedule}
        self.check_configuration()
        if self.store.scalar('SELECT COUNT(*) FROM agents'):
            self.check_progress()

    def check_progress(self):
        """A committed phase cannot silently omit its declared inputs."""
        self.check_invariants()
        meta = self.store.get_meta()
        frontier = int(meta['tick'])
        if meta['active_tick'] is not None and meta['next_phase'] != 'NIGHT_CLOSE':
            frontier = int(meta['active_tick'])
        completed = {row['input_key'] for row in self.store.query('SELECT input_key FROM population_scenario_receipts')}
        if any(entry['tick'] <= frontier and entry['key'] not in completed for entry in self.schedule):
            raise ResidenceError('committed World phase lacks a declared population input')

    def check_configuration(self):
        if parse_schedule(self.e.config, self.e.engine_semantics_version) != self.schedule:
            raise ResidenceError('population scenario changed after construction')
        meta = self.store.get_meta()
        if meta is None or parse_schedule(json.loads(meta['config_json']), 21) != self.schedule:
            raise ResidenceError('population scenario disagrees with the recorded run configuration')

    def _event(self, tick, kind, payload):
        return self.store.log_event(tick, kind, json.loads(_json(payload)),
            phase='GENESIS' if tick == 0 else 'NIGHT_CLOSE',
            subject_type='population_scenario', subject_id=1, importance=0.5)

    def declare(self):
        self.check_configuration()
        if not self.schedule:
            self.check_invariants()
            return
        with self.store.savepoint('population_scenario_declare'):
            if not self.store.scalar('SELECT COUNT(*) FROM population_scenario_manifest'):
                if self.store.tick != 0 or self.store.active_tick is not None:
                    raise ResidenceError('population scenario must be declared at genesis')
                event = self._event(0, 'population_scenario_declared', {'version': 1, 'schedule': self.schedule})
                self.store.insert('population_scenario_manifest', id=1, schedule_json=_json(self.schedule), event_id=event)
            self.apply(0)

    @staticmethod
    def _references(entry):
        references = {entry['actor']}
        if entry['action'] == 'propose':
            references.update(entry['members'])
            for disposition in entry['care_plan']:
                references.update(disposition.values())
        return references

    def _resolve(self, key, tick):
        rows = self.store.query(
            "SELECT DISTINCT subject_id FROM events WHERE kind IN ('person_registered','birth') "
            "AND subject_type='agent' AND tick<=? AND json_extract(payload_json,'$.random_key')=?",
            (tick, key))
        if not rows:
            raise MovementError('unknown_person_origin:' + key)
        if len(rows) != 1:
            raise ResidenceError('population origin key identifies multiple people')
        actor = int(rows[0]['subject_id'])
        if person_key(self.store, actor) != key:
            raise ResidenceError('population origin disagrees with recorded person identity')
        # Missing or corrupt history is a source failure, never an input rejection.
        self.e.population.history.state_at(actor, tick)
        return actor

    def _execute(self, entry, resolved):
        actor, tick = resolved[entry['actor']], entry['tick']
        phase = 'GENESIS' if tick == 0 else 'NIGHT_CLOSE'
        if entry['action'] == 'propose':
            return self.e.population.propose(tick, actor, entry['cause'],
                [resolved[key] for key in entry['members']], 'scenario:' + entry['key'],
                due_tick=entry['due_tick'], destination_region_id=entry['destination_region_id'],
                care_plan=[{'child_id': resolved[item['child']], 'guardian_id': resolved[item['guardian']]}
                           for item in entry['care_plan']], phase=phase)
        receipt = self.store.query_one('SELECT * FROM population_scenario_receipts WHERE input_key=?',
                                      (entry['proposal'],))
        if receipt is None or receipt['outcome'] != 'accepted':
            raise MovementError('proposal_was_rejected')
        movement = json.loads(receipt['result_json'])['movement_id']
        return self.e.population.respond(tick, actor, movement, entry['decision'], phase=phase)

    def apply(self, tick):
        self.check_invariants()
        _integer(tick, 'tick')
        if not self.schedule:
            return
        completed = {row['input_key'] for row in self.store.query('SELECT input_key FROM population_scenario_receipts')}
        if any(entry['tick'] < tick and entry['key'] not in completed for entry in self.schedule):
            raise ResidenceError('population scenario missed its execution day')
        pending = [entry for entry in self.schedule if entry['tick'] == tick and entry['key'] not in completed]
        if not pending:
            return
        if ((tick == 0 and (self.store.tick != 0 or self.store.active_tick is not None))
                or (tick > 0 and (self.store.active_tick != tick or self.store.next_phase != 'NIGHT_CLOSE'
                    or self.store.scalar('SELECT COUNT(*) FROM population_resident_census WHERE tick>=?', (tick,))))):
            raise ResidenceError('population inputs require their uncompleted World phase')
        with self.store.savepoint('population_scenario_inputs'):
            for entry in pending:
                resolved, result, reason = {}, None, ''
                try:
                    for key in sorted(self._references(entry)):
                        resolved[key] = self._resolve(key, tick)
                    result = self._execute(entry, resolved)
                except MovementError as exc:
                    reason = str(exc)
                payload = {'input_key': entry['key'], 'outcome': 'rejected' if reason else 'accepted',
                           'reason': reason, 'resolved': resolved, 'result': result}
                event = self._event(tick, 'population_scenario_input', payload)
                self.store.insert('population_scenario_receipts', input_key=entry['key'], tick=tick,
                    outcome=payload['outcome'], reason=reason, resolved_json=_json(resolved),
                    result_json=_json(result), event_id=event)
            self.check_invariants()

    def check_invariants(self):
        self.check_configuration()
        manifest = self.store.query_one('SELECT * FROM population_scenario_manifest WHERE id=1')
        receipts = self.store.query('SELECT * FROM population_scenario_receipts ORDER BY event_id')
        if not self.schedule:
            if manifest or receipts:
                raise ResidenceError('unexpected population scenario evidence')
            return
        if not manifest or manifest['schedule_json'] != _json(self.schedule):
            raise ResidenceError('population scenario declaration is missing or changed')
        self._check_event(manifest['event_id'], 0, 'population_scenario_declared',
                          {'version': 1, 'schedule': self.schedule})
        expected_keys = [entry['key'] for entry in self.schedule]
        actual_keys = [row['input_key'] for row in receipts]
        if actual_keys != expected_keys[:len(actual_keys)]:
            raise ResidenceError('population input receipts are not an ordered schedule prefix')
        for row in receipts:
            entry = self.inputs[row['input_key']]
            resolved, result = json.loads(row['resolved_json']), json.loads(row['result_json'])
            payload = {'input_key': row['input_key'], 'outcome': row['outcome'], 'reason': row['reason'],
                       'resolved': resolved, 'result': result}
            if row['tick'] != entry['tick'] or row['event_id'] <= manifest['event_id']:
                raise ResidenceError('population input day or declaration frontier changed')
            self._check_event(row['event_id'], row['tick'], 'population_scenario_input', payload)
            if not resolved.keys() <= self._references(entry):
                raise ResidenceError('population input resolved undeclared people')
            for key, actor in resolved.items():
                if type(actor) is not int or self._resolve(key, row['tick']) != actor:
                    raise ResidenceError('population input person binding changed')
            if row['outcome'] == 'accepted':
                if resolved.keys() != self._references(entry) or row['reason'] or not isinstance(result, dict):
                    raise ResidenceError('accepted population input lacks its resolved result')
                movement = self.e.population._read(result['movement_id'])
                proposal = entry if entry['action'] == 'propose' else self.inputs[entry['proposal']]
                if (movement['request_key'] != 'scenario:' + proposal['key']
                        or movement['created_tick'] != proposal['tick']
                        or movement['due_tick'] != proposal['due_tick']
                        or movement['actor_id'] != self._resolve(proposal['actor'], proposal['tick'])
                        or movement['proposal_event_id'] >= row['event_id']):
                    raise ResidenceError('population input is bound to another movement')
                terms = self.e.population._terms(proposal['cause'],
                    [self._resolve(key, proposal['tick']) for key in proposal['members']],
                    proposal['destination_region_id'],
                    [{'child_id': self._resolve(item['child'], proposal['tick']),
                      'guardian_id': self._resolve(item['guardian'], proposal['tick'])}
                     for item in proposal['care_plan']])
                if movement['terms_json'] != _json(terms):
                    raise ResidenceError('population movement disagrees with its declared terms')
                closed = movement['outcome_event_id'] is not None and movement['outcome_event_id'] < row['event_id']
                expected_result = {'movement_id': movement['id'], 'due_tick': movement['due_tick'],
                    'status': movement['status'] if closed else 'pending',
                    'closed_tick': movement['closed_tick'] if closed else None,
                    'reason': movement['reason'] if closed else None,
                    'destination_household_id': movement['destination_household_id'] if closed else None}
                if _json(result) != _json(expected_result):
                    raise ResidenceError('population input result disagrees with its event frontier')
                if entry['action'] == 'respond':
                    assent = self.store.query_one(
                        'SELECT event_id FROM population_movement_assents WHERE movement_id=? AND actor_id=? '
                        'AND tick=? AND decision=?', (movement['id'], resolved[entry['actor']], row['tick'], entry['decision']))
                    cancelled = movement['closed_tick'] == row['tick'] and movement['reason'] == 'household_snapshot_changed'
                    if not ((assent and assent['event_id'] < row['event_id'])
                            or (cancelled and movement['outcome_event_id'] < row['event_id'])):
                        raise ResidenceError('population response lacks its assent or invalidation')
            elif row['outcome'] != 'rejected' or not row['reason'] or result is not None:
                raise ResidenceError('invalid population input rejection')

    def _check_event(self, event_id, tick, kind, payload):
        event = self.store.query_one('SELECT * FROM events WHERE id=?', (event_id,))
        if (event is None or event['tick'] != tick or event['kind'] != kind
                or event['phase'] != ('GENESIS' if tick == 0 else 'NIGHT_CLOSE')
                or event['subject_type'] != 'population_scenario' or event['subject_id'] != 1
                or _json(json.loads(event['payload_json'])) != _json(payload)):
            raise ResidenceError('population scenario event disagrees with its record')
