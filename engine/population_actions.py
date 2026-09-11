"""Private household movement choices; no economic or memory writes."""
import json

from .population import MovementInvalidated


def movement_context(population, actor_id, tick):
    population._require_enabled()
    store = population.store
    actor = store.query_one('SELECT alive,age FROM agents WHERE id=?', (actor_id,))
    if actor is None or not actor['alive'] or actor['age'] < 18:
        return None
    resident = population.is_available(actor_id)
    result = {'residence': 'resident' if resident else 'outside',
              'local_activity_allowed': resident,
              'accounting_policy': 'retained_assets_no_transfer_v1',
              'pending_movements': [], 'eligible_responses': [], 'proposal_template': None}
    try:
        snapshot = population._snapshot(actor_id, tick)
    except MovementInvalidated as exc:
        result['unavailable_reason'] = str(exc)
        return result
    result['household_id'] = snapshot['household_id']
    result['members'] = [{key: member[key] for key in ('agent_id', 'adult', 'guardian_id')}
                         for member in snapshot['members']]
    for member in result['members']:
        member['name'] = store.scalar('SELECT name FROM agents WHERE id=?', (member['agent_id'],))
    pending = store.query("SELECT id FROM population_movements WHERE household_id=? AND status='pending' ORDER BY id",
                          (snapshot['household_id'],))
    for candidate in pending:
        row = population._read(candidate['id'])
        terms, original = json.loads(row['terms_json']), json.loads(row['snapshot_json'])
        if actor_id not in original['adult_ids']:
            continue
        assents = []
        for assent in store.query('SELECT * FROM population_movement_assents WHERE movement_id=? ORDER BY id', (row['id'],)):
            population._check_event(assent['event_id'], assent['tick'], assent['actor_id'],
                'population_movement_assent', {'movement_id': row['id'], 'decision': assent['decision']})
            assents.append({key: assent[key] for key in ('actor_id', 'decision', 'tick')})
        result['pending_movements'].append({'movement_id': row['id'], 'proposer_id': row['actor_id'],
            'due_tick': row['due_tick'], 'terms': terms, 'required_adult_ids': original['adult_ids'], 'assents': assents})
        if tick < row['due_tick'] and (resident or terms['cause'] == 'return'):
            accepted = any(item['actor_id'] == actor_id and item['decision'] == 'accept' for item in assents)
            for decision in (('withdraw',) if accepted else ('accept', 'decline')):
                result['eligible_responses'].append({'type': 'respond_population_movement',
                    'movement_id': row['id'], 'decision': decision})
    if pending:
        return result
    if any(population.e.families.pending_interests(adult) for adult in snapshot['adult_ids']):
        result['unavailable_reason'] = 'An affected adult has a pending household agreement.'
        return result
    template = {'type': 'propose_population_movement', 'cause': 'departure' if resident else 'return',
                'member_ids': [member['agent_id'] for member in snapshot['members']],
                'care_plan': [{'child_id': member['agent_id'], 'guardian_id': member['guardian_id']}
                              for member in snapshot['members'] if not member['adult']],
                'request_key': f'population-{actor_id}-{tick}', 'due_tick': tick + 2}
    if not resident:
        regions = [dict(row) for row in store.query('SELECT id,name FROM regions ORDER BY id LIMIT 128')]
        result['return_regions'] = regions
        if not regions:
            result['unavailable_reason'] = 'No modeled return region exists.'
            return result
        template['destination_region_id'] = (snapshot['region_id'] if any(
            row['id'] == snapshot['region_id'] for row in regions) else regions[0]['id'])
    result['proposal_template'] = template
    return result
