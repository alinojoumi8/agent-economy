"""Versioned Commons input receipts; private text remains in its owning row."""
from __future__ import annotations

import hashlib
import inspect
import json


KIND = 'commons_operation_recorded'
VERSION = 1
# operation: (result key, owning table, primary key, actor column, text fields)
OPERATIONS = {
    'ensure_profile': ('agent_id', 'commons_profiles', 'agent_id', 'agent_id', {'biography': ('biography', 500)}),
    'create_community': ('id', 'commons_communities', 'id', 'owner_agent_id',
                         {'name': ('name', 120), 'description': ('description', 1000)}),
    'publish': ('id', 'commons_entries', 'id', 'author_agent_id', {'body': ('body_text', 3000)}),
    'moderate': ('moderation_action_id', 'commons_moderation_actions', 'id', 'moderator_agent_id',
                 {'reason': ('reason', 500)}),
    'appeal': ('appeal_id', 'commons_appeals', 'id', 'appellant_agent_id', {'body': ('body_text', 1000)}),
    'join_community': (None, None, None, None, {}),
    'follow': (None, None, None, None, {}),
    'react': (None, None, None, None, {}),
    'feed': (None, None, None, None, {}),
    'read': (None, None, None, None, {}),
}


class CommonsReplayError(RuntimeError):
    pass


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def arguments_for(operation, service, args, kwargs):
    bound = inspect.signature(operation).bind(service, *args, **kwargs)
    bound.apply_defaults()
    values = dict(bound.arguments)
    values.pop('self')
    actor_name = next(iter(values))
    actor = values.pop(actor_name)
    if type(actor) is not int:
        raise ValueError('Commons actor must be an integer')
    for name, value in values.items():
        if name.endswith('_id') and value is not None and (type(value) is not int or value < 1):
            raise ValueError(f'{name} must be a positive integer')
        if name == 'active' and type(value) is not bool:
            raise ValueError('active must be a boolean')
        if name == 'limit' and type(value) is not int:
            raise ValueError('limit must be an integer')
    return actor, values


def record(service, operation, actor, values, result, frontier):
    key, _, _, _, fields = OPERATIONS[operation]
    arguments = {name: value for name, value in values.items() if name not in fields}
    text_hashes = {name: canonical_hash(str(values[name]).strip()[:limit])
                   for name, (_, limit) in fields.items()}
    payload = {'version': VERSION, 'operation': operation, 'actor_id': actor,
               'arguments': arguments, 'text_hashes': text_hashes,
               'result_id': int(result[key]) if key else None,
               'result_hash': canonical_hash(result), 'frontier_event_id': frontier}
    # Validate finite, JSON-compatible input before persisting the receipt. The
    # operation savepoint also rolls back its effects if encoding fails.
    canonical_hash(payload)
    service.store.log_event(service.store.tick, KIND, payload, phase='COMMONS',
                            subject_type='agent', subject_id=actor, importance=0.0)


def decode(service, source, event):
    """Preflight a recorded command without changing source or replay state."""
    try:
        data = json.loads(event['payload_json'])
        if not isinstance(data, dict) or set(data) != {
                'version', 'operation', 'actor_id', 'arguments', 'text_hashes',
                'result_id', 'result_hash', 'frontier_event_id'}:
            raise ValueError('invalid receipt shape')
        if type(data['version']) is not int or data['version'] != VERSION:
            raise ValueError('unsupported receipt version')
        name = data['operation']
        if name not in OPERATIONS:
            raise ValueError('unsupported operation')
        actor = data['actor_id']
        if type(actor) is not int or actor != event['subject_id'] or event['subject_type'] != 'agent':
            raise ValueError('invalid actor binding')
        if event['phase'] != 'COMMONS' or event['kind'] != KIND or event['tick'] != service.store.tick:
            raise ValueError('invalid input boundary')
        frontier = data['frontier_event_id']
        if type(frontier) is not int or frontier < 0 or frontier >= event['id']:
            raise ValueError('invalid event frontier')
        if not isinstance(data['result_hash'], str) or len(data['result_hash']) != 64:
            raise ValueError('invalid result hash')
        method = getattr(service, name)
        parameters = list(inspect.signature(method).parameters)[1:]
        _, table, primary, actor_column, fields = OPERATIONS[name]
        if not isinstance(data['arguments'], dict) or set(data['arguments']) != set(parameters) - fields.keys():
            raise ValueError('invalid operation arguments')
        if not isinstance(data['text_hashes'], dict) or set(data['text_hashes']) != fields.keys():
            raise ValueError('invalid text bindings')
        values = dict(data['arguments'])
        if table:
            if type(data['result_id']) is not int or data['result_id'] < 1:
                raise ValueError('invalid content reference')
            row = source.execute(f'SELECT * FROM {table} WHERE {primary}=?', (data['result_id'],)).fetchone()
            if row is None or row[actor_column] != actor or row['created_tick'] != event['tick']:
                raise ValueError('missing, future or mismatched content reference')
            for param, (column, _) in fields.items():
                values[param] = str(row[column])
                if canonical_hash(values[param]) != data['text_hashes'][param]:
                    raise ValueError('changed content reference')
        elif data['result_id'] is not None:
            raise ValueError('unexpected content reference')
        inspect.signature(method).bind(actor, **values)
        arguments_for(method.__func__.__wrapped__, service, (actor,), values)
        for param, table, day_column in [
                ('entry_id', 'commons_entries', 'created_tick'),
                ('parent_entry_id', 'commons_entries', 'created_tick'),
                ('community_id', 'commons_communities', 'created_tick'),
                ('moderation_action_id', 'commons_moderation_actions', 'created_tick'),
                ('impression_id', 'commons_feed_impressions', 'delivered_tick'),
                ('claim_id', 'claims', 'tick')]:
            if values.get(param) is None:
                continue
            ref = source.execute(f'SELECT * FROM {table} WHERE id=?', (values[param],)).fetchone()
            if ref is None or ref[day_column] > event['tick']:
                raise ValueError('missing or future argument reference')
            if 'created_event_id' in ref.keys() and ref['created_event_id'] is not None and ref['created_event_id'] > frontier:
                raise ValueError('argument reference follows the input frontier')
            if param == 'impression_id' and ref['viewer_agent_id'] != actor:
                raise ValueError('impression belongs to another viewer')
        if values.get('target_agent_id') is not None:
            service._living_agent(values['target_agent_id'])
        canonical_hash(values)
    except (TypeError, ValueError, KeyError) as exc:
        raise CommonsReplayError(f'invalid recorded Commons input: {exc}') from exc
    service._local_agent(actor)
    return data, actor, values
