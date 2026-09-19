"""Chart series with explicit gaps for undefined resident rates."""
import json
import math

from research.metric_registry import resident_rate_unavailable_reason


RESIDENT_RATES = frozenset({'unemployment', 'resident_unemployment', 'sentiment', 'resident_sentiment'})


def metric_series_for_display(connection, names: list[str]) -> dict:
    meta = connection.execute('SELECT * FROM run_meta LIMIT 1').fetchone()
    semantics = int(json.loads(meta['config_json']).get('engine_semantics_version', 1))
    if semantics < 21:
        return {name: [dict(tick=int(row[0]), value=float(row[1])) for row in connection.execute(
            'SELECT tick,value FROM metrics WHERE name=? ORDER BY tick', (name,))] for name in names}
    end_tick = int(meta['tick'])
    if meta['active_tick'] is not None:
        end_tick = min(end_tick, int(meta['active_tick']) - 1)
    # Read all requested observations once; avoid one database query per chart day.
    requested = sorted(set(names) | {'resident_labor_force', 'resident_sentiment_observations'})
    if not names:
        return {}
    placeholders = ','.join('?' for _ in requested)
    rows = connection.execute(
        f'SELECT name,tick,value FROM metrics WHERE tick<=? AND name IN ({placeholders}) ORDER BY tick,id',
        (end_tick, *requested)).fetchall()
    by_name = {name: {} for name in requested}
    for row in rows:
        by_name[row['name']][row['tick']] = row['value']
    result = {}
    for name in names:
        values = by_name[name]
        if name not in RESIDENT_RATES:
            result[name] = [dict(tick=tick, value=value) for tick, value in values.items()]
            continue
        denominator = 'resident_labor_force' if 'unemployment' in name else 'resident_sentiment_observations'
        points = []
        for tick in range(end_tick + 1):
            reason = resident_rate_unavailable_reason(name, by_name[denominator].get(tick))
            value = values.get(tick)
            if reason is None:
                reason = ('not_recorded_at_tick' if value is None else
                          'nonfinite_value' if not isinstance(value, (int, float)) or not math.isfinite(value) else None)
            points.append(dict(tick=tick, value=value if reason is None else None,
                               status='available' if reason is None else 'unavailable', reason=reason))
        result[name] = points
    return result
