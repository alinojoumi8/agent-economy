"""Restore draft population inputs in event order at a committed day boundary."""
from __future__ import annotations

import json

from engine.store import open_read_only_connection
from world.commons import CommonsService
from world.commons_journal import CommonsReplayError, KIND, decode


EVENT_COLUMNS = 'id,tick,phase,kind,subject_type,subject_id,importance,payload_json'
MANUAL = {'participant_control_acquired', 'participant_control_released',
          'participant_action_queued', 'participant_action_replaced'}
EXTERNAL = {'external_action_queued', 'external_action_rejected', 'external_action_stale'}


def _event_document(row):
    result = dict(row)
    result['payload_json'] = json.loads(result['payload_json'])
    return result


def _events(source, store, first, last):
    sql = f'SELECT {EVENT_COLUMNS} FROM events WHERE id>? AND id<=? ORDER BY id'
    expected = [_event_document(row) for row in source.execute(sql, (first, last))]
    actual = [_event_document(row) for row in store.query(sql, (first, last))]
    if expected != actual:
        raise CommonsReplayError('recorded input event sequence does not match replay')


def _copy_event(store, event):
    value = json.loads(event['payload_json'])
    local = store.log_event(event['tick'], event['kind'], value, phase=event['phase'],
        subject_type=event['subject_type'], subject_id=event['subject_id'], importance=event['importance'])
    if local != event['id']:
        raise CommonsReplayError('recorded input event ID does not match replay')


def _manual_input(service, source, event, *, validate_only=False):
    """Control events retain original actions even when a queue row was replaced."""
    store, participant = service.store, service.participant
    payload = json.loads(event['payload_json'])
    actor = payload.get('agent_id')
    if type(actor) is not int or actor != event['subject_id']:
        raise CommonsReplayError('invalid recorded participant actor')
    kind = event['kind']
    person = store.query_one('SELECT * FROM agents WHERE id=?', (actor,))
    if person is None:
        raise CommonsReplayError('recorded participant person is missing')
    action_row = None
    if kind == 'participant_control_acquired' and not participant._controllable(person):
        raise CommonsReplayError('recorded participant control has no available adult')
    if kind in {'participant_action_queued', 'participant_action_replaced'}:
        if payload.get('target_tick') != store.tick + 1 or not isinstance(payload.get('action'), dict):
            raise CommonsReplayError('invalid recorded participant action boundary')
        participant.normalize_action(actor, payload['action'])
        action_row = source.execute('SELECT * FROM participant_actions WHERE agent_id=? AND target_tick=?',
                                    (actor, payload['target_tick'])).fetchone()
        if action_row is None:
            raise CommonsReplayError('recorded participant action row is missing')
    if validate_only:
        return
    if kind == 'participant_control_acquired':
        store.execute('INSERT INTO participant_control(id,agent_id,active,acquired_tick,updated_at) '
            'VALUES(1,?,1,?,?) ON CONFLICT(id) DO UPDATE SET agent_id=excluded.agent_id,'
            'active=1,acquired_tick=excluded.acquired_tick,updated_at=excluded.updated_at',
            (actor, store.tick, 'recorded-replay'))
    elif kind == 'participant_control_released':
        store.execute("UPDATE participant_control SET active=0,updated_at='recorded-replay' WHERE id=1")
        store.execute("UPDATE participant_actions SET status='cancelled' WHERE agent_id=? "
                      "AND target_tick>? AND status='queued'", (actor, store.tick))
    else:
        store.execute('INSERT INTO participant_actions(id,agent_id,target_tick,action_json,reasoning,status,'
            'result_json,source_action_id,created_at,executed_at) VALUES(?,?,?,?,?,\'queued\',NULL,?,?,NULL) '
            'ON CONFLICT(agent_id,target_tick) DO UPDATE SET action_json=excluded.action_json,'
            'reasoning=excluded.reasoning,status=\'queued\',result_json=NULL,executed_at=NULL',
            (action_row['id'], actor, payload['target_tick'], json.dumps(payload['action']),
             action_row['reasoning'], action_row['id'], action_row['created_at']))
    store.set_meta(participant_influenced=1)
    _copy_event(store, event)


def _external_binding(source, event):
    data = json.loads(event['payload_json'])
    row = source.execute('SELECT * FROM external_action_submissions WHERE id=?',
                         (data.get('submission_id'),)).fetchone()
    if (row is None or row['connection_id'] != data.get('connection_id')
            or row['actor_id'] != data.get('actor_id') or row['actor_id'] != event['subject_id']
            or row['target_tick'] != data.get('target_tick') or row['target_tick'] != event['tick'] + 1):
        raise CommonsReplayError('invalid recorded external action binding')
    return row


def _copy_rejected_external(service, source, event):
    """Keep negative input receipts; they never become executable decisions."""
    row = _external_binding(source, event)
    if row['status'] not in {'rejected', 'stale'}:
        raise CommonsReplayError('negative external input has a nonnegative source status')
    for table, primary, identity in [('external_agent_connections', 'id', row['connection_id']),
                                     ('external_agent_turns', 'id', row['turn_id']),
                                     ('external_action_submissions', 'id', row['id'])]:
        if identity is None or service.store.query_one(f'SELECT 1 FROM {table} WHERE {primary}=?', (identity,)):
            continue
        recorded = source.execute(f'SELECT * FROM {table} WHERE {primary}=?', (identity,)).fetchone()
        if recorded is None:
            raise CommonsReplayError('negative external input dependency is missing')
        service.store.insert(table, **dict(recorded))
    _copy_event(service.store, event)


def _arrival_profile(source, store, profile):
    """Arrival binding creates a profile as an endogenous part of NIGHT_CLOSE."""
    sql = ('SELECT id,actor_id,spawned_tick,schedule_event_id FROM external_actor_requests '
           "WHERE actor_id=? AND spawned_tick=? AND status='spawned'")
    params = (profile['agent_id'], profile['created_tick'])
    recorded = source.execute(sql, params).fetchone()
    local = store.query_one(sql, params)
    if recorded is None or local is None or tuple(recorded) != tuple(local):
        return False
    existing = store.query_one('SELECT * FROM commons_profiles WHERE agent_id=?', (profile['agent_id'],))
    return existing is not None and all(existing[key] == profile[key]
        for key in ('agent_id', 'display_name', 'biography', 'created_tick'))


def restore_population_inputs(service, tick):
    store = service.store
    if store.active_tick is not None or store.tick != int(tick) - 1:
        raise CommonsReplayError('recorded inputs require the matching committed day boundary')
    source = open_read_only_connection(service.config['replay_source_path'],
                                      require_closed=service.config.get('replay_source_closed') is True)
    try:
        commons = CommonsService(service.economy)
        initial = int(store.scalar('SELECT COALESCE(MAX(id),0) FROM events'))
        events = source.execute(f'SELECT {EVENT_COLUMNS} FROM events WHERE tick=? ORDER BY id',
                                (store.tick,)).fetchall()
        receipts = [event for event in events if event['kind'] == KIND]
        prepared = []
        spans = []
        for event in receipts:
            data, actor, values = decode(commons, source, event)
            frontier = data['frontier_event_id']
            if spans and frontier < spans[-1][1]:
                raise CommonsReplayError('overlapping recorded Commons commands')
            spans.append((frontier, event['id']))
            prepared.append((event['id'], frontier, event, (data, actor, values)))
        for event in events:
            if event['phase'] == 'COMMONS' and not any(first < event['id'] <= last for first, last in spans):
                raise CommonsReplayError('Commons input ordering is missing; pre-receipt draft source cannot be replayed')
        # Profiles and empty feeds have no legacy command event. A source with
        # these rows and no receipt cannot be silently treated as an empty batch.
        if not receipts:
            for table, column in [('commons_profiles', 'created_tick'), ('commons_communities', 'created_tick'),
                                  ('commons_follows', 'created_tick'), ('commons_feed_impressions', 'delivered_tick'),
                                  ('commons_appeals', 'created_tick')]:
                for row in source.execute(f'SELECT * FROM {table} WHERE {column}=?', (store.tick,)):
                    if table == 'commons_profiles' and _arrival_profile(source, store, row):
                        continue
                    raise CommonsReplayError('Commons input ordering is missing; pre-receipt draft source cannot be replayed')
        requests = {row['schedule_event_id']: row['id'] for row in source.execute(
            'SELECT id,schedule_event_id FROM external_actor_requests WHERE requested_tick=?', (store.tick,))}
        request_ids, submission_ids = set(), set()
        for event in events:
            if event['id'] in requests:
                prepared.append((event['id'], event['id'] - 1, event, None))
                if event['id'] > initial:
                    request_ids.add(requests[event['id']])
            elif event['phase'] == 'CONTROL' and not any(first < event['id'] <= last for first, last in spans):
                if event['id'] <= initial:
                    _events(source, store, event['id'] - 1, event['id'])
                    continue
                if event['kind'] not in MANUAL | EXTERNAL:
                    raise CommonsReplayError(f"unsupported recorded boundary input: {event['kind']}")
                if event['kind'] in MANUAL:
                    _manual_input(service, source, event, validate_only=True)
                else:
                    row = _external_binding(source, event)
                    if event['kind'] == 'external_action_queued':
                        submission_ids.add(row['id'])
                prepared.append((event['id'], event['id'] - 1, event, None))
        if request_ids:
            service._restore_replay_actor_requests(tick, request_ids=request_ids, validate_only=True)
        if submission_ids:
            service._replay_decisions(tick, before_night=True, submission_ids=submission_ids,
                                      validate_only=True, restore_turns=False)
        # Every reference/actor known before execution has now been checked. The
        # remaining result and event comparisons are transactional as one batch.
        with store.savepoint('population_recorded_inputs'):
            for last, frontier, event, command in sorted(prepared, key=lambda item: item[0]):
                current = int(store.scalar('SELECT COALESCE(MAX(id),0) FROM events'))
                if last <= current:
                    _events(source, store, frontier, last)
                    continue
                if current != frontier:
                    raise CommonsReplayError('recorded input frontier does not match replay')
                if command is not None:
                    data, actor, values = command
                    getattr(commons, data['operation'])(actor, **values)
                elif event['id'] in requests:
                    service._restore_replay_actor_requests(tick, request_ids={requests[event['id']]})
                elif event['kind'] in MANUAL:
                    _manual_input(service, source, event)
                elif event['kind'] == 'external_action_queued':
                    service._replay_decisions(tick, before_night=True,
                        submission_ids={json.loads(event['payload_json'])['submission_id']}, restore_turns=False)
                else:
                    _copy_rejected_external(service, source, event)
                _events(source, store, frontier, last)
                if int(store.scalar('SELECT COALESCE(MAX(id),0) FROM events')) != last:
                    raise CommonsReplayError('recorded input result does not match replay')
    finally:
        source.close()
