"""Forms for the shared, private population movement context."""


def population_action_catalog(context, tick):
    if not context:
        return []
    items = []
    for action in context.get('eligible_responses', []):
        items.append({'type': action['type'], 'variant': f"movement-{action['movement_id']}-{action['decision']}",
            'label': f"{action['decision'].capitalize()} movement {action['movement_id']}",
            'fields': [{'name': key, 'kind': 'hidden', 'default': value}
                       for key, value in action.items() if key != 'type']})
    template = context.get('proposal_template')
    if template:
        fields = [
            {'name': 'cause', 'kind': 'hidden', 'default': template['cause']},
            {'name': 'member_ids', 'kind': 'people', 'label': 'Who is moving?',
             'default': template['member_ids'], 'max_length': 4096,
             'options': [{'value': person['agent_id'], 'label': person['name']} for person in context['members']]},
            {'name': 'care_plan', 'kind': 'care', 'label': 'Who will care for each child?',
             'default': template['care_plan'], 'max_length': 16384,
             'children': [{'id': person['agent_id'], 'name': person['name']} for person in context['members'] if not person['adult']],
             'options': [{'value': person['agent_id'], 'label': person['name']} for person in context['members'] if person['adult']]},
            {'name': 'due_tick', 'kind': 'number', 'label': 'Move on day',
             'default': template['due_tick'], 'min': tick + 1},
            {'name': 'request_key', 'kind': 'text', 'label': 'Request reference',
             'default': template['request_key'], 'max_length': 96},
        ]
        if template['cause'] == 'return':
            fields.append({'name': 'destination_region_id', 'kind': 'select', 'label': 'Return region',
                'default': template['destination_region_id'],
                'options': [{'value': row['id'], 'label': row['name']} for row in context['return_regions']]})
        items.append({'type': 'propose_population_movement', 'variant': 'default',
                      'label': 'Propose departure' if template['cause'] == 'departure' else 'Request return',
                      'fields': fields})
    for item in items:
        item.update(enabled=True, category='population', channel='world')
    return items
