"""Versioned startup menus carried across a committed MORNING boundary."""
import hashlib
import json


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def capture_startup_authorizations(tick, authorizations):
    actors = [{'actor_id': actor, 'actions': actions}
              for (day, actor), actions in sorted(authorizations.items()) if day == tick]
    body = {'version': 1, 'tick': tick, 'actors': actors}
    frame = {**body, 'sha256': hashlib.sha256(_canonical(body).encode()).hexdigest()}
    # Detach the saved state from the mutable context-builder cache.
    return json.loads(_canonical(frame))


def restore_startup_authorizations(tick, frame):
    """Validate the complete saved menu before replacing the live cache.

    Its checksum detects corruption; checkpoint/study manifests bind the saved
    phase state to an artifact. Execution still validates every economic action.
    """
    error = 'invalid saved startup authorizations'
    if not isinstance(frame, dict) or set(frame) != {'version', 'tick', 'actors', 'sha256'}:
        raise ValueError(error)
    if type(frame['version']) is not int or frame['version'] != 1:
        raise ValueError(error + ': unsupported version')
    if type(frame['tick']) is not int or frame['tick'] != tick:
        raise ValueError(error + ': wrong tick')
    if not isinstance(frame['actors'], list):
        raise ValueError(error + ': actor list required')
    body = {key: frame[key] for key in ('version', 'tick', 'actors')}
    try:
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ValueError(error + ': noncanonical payload') from exc
    if frame['sha256'] != digest:
        raise ValueError(error + ': checksum mismatch')
    restored = {}
    previous = 0
    for entry in frame['actors']:
        if not isinstance(entry, dict) or set(entry) != {'actor_id', 'actions'}:
            raise ValueError(error + ': invalid actor entry')
        actor = entry['actor_id']
        if type(actor) is not int or actor <= previous:
            raise ValueError(error + ': actors must be positive, unique and ordered')
        actions = entry['actions']
        if not isinstance(actions, list) or any(
                not isinstance(action, dict) or not isinstance(action.get('type'), str)
                or not action['type'] for action in actions):
            raise ValueError(error + ': invalid action list')
        restored[(tick, actor)] = json.loads(_canonical(actions))
        previous = actor
    return restored
