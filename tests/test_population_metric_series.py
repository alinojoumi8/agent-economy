"""Observer series share exact-day rate validity with the research reader."""
import json

import pytest

from research.metric_registry import read_metric_observation
from server.projections.metric_series import metric_series_for_display
from server.replay import ReplayReader
from world.metrics import Metrics
from .test_population_metrics import boundary, depart
from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case


def test_empty_days_are_explicit_gaps_in_live_and_replay_series(residence_case, monkeypatch):
    c = residence_case
    c.e.store.execute('UPDATE agents SET age=30,retired=0')
    c.e.store.execute("INSERT INTO beliefs(agent_id,key,value,updated_tick) VALUES(?,'sentiment',0.5,0)", (c.person,))
    boundary(c, 0)
    Metrics(c.e, semantics_version=21).snapshot(0)
    for person in (c.person, c.heir):
        depart(c, person)
    boundary(c, 1)
    Metrics(c.e, semantics_version=21).snapshot(1)
    c.history.transition(2, c.person, 'return', previous_id=c.history.state_at(c.person, 1)['id'], request_key='return-test')
    boundary(c, 2)
    Metrics(c.e, semantics_version=21).snapshot(2)
    c.e.store.record_metric(3, 'unemployment', 0.25)  # Future fixture must not be returned.
    names = ['unemployment', 'resident_unemployment', 'sentiment', 'resident_sentiment']
    before = contents(c.e.store)
    series = metric_series_for_display(c.e.store.conn, names)
    for name in names:
        assert [row['tick'] for row in series[name]] == [0, 1, 2]
        assert series[name][0]['value'] is not None and series[name][2]['value'] is not None
        assert series[name][1]['value'] is None
        for point in series[name]:
            research = read_metric_observation(c.e.store, name, point['tick'])
            assert all(point[key] == research[key] for key in ('tick', 'value', 'status', 'reason'))
    reader = ReplayReader()
    monkeypatch.setattr(reader, '_conn', lambda _run: c.e.store.conn)
    assert reader.metrics('fixture', ','.join(names)) == series
    assert contents(c.e.store) == before


@pytest.mark.parametrize('denominator', [None, 0, -1, 0.5, 'invalid', float('inf')])
def test_invalid_counts_cannot_resurrect_a_stale_rate(residence_case, denominator):
    c = residence_case
    boundary(c, 2)
    c.e.store.record_metric(0, 'unemployment', 0.6)
    c.e.store.record_metric(0, 'resident_labor_force', 2)
    c.e.store.record_metric(2, 'unemployment', 0.9)
    if denominator is not None:
        # Direct insertion deliberately models a damaged stored observation.
        c.e.store.insert('metrics', tick=2, name='resident_labor_force', value=denominator)
    latest = metric_series_for_display(c.e.store.conn, ['unemployment'])['unemployment'][-1]
    assert latest['tick'] == 2 and latest['value'] is None
    assert latest['reason'] == read_metric_observation(c.e.store, 'unemployment', 2)['reason']


def test_active_day_is_not_a_committed_rate_observation(residence_case):
    c = residence_case
    boundary(c, 2)
    c.e.store.execute('UPDATE run_meta SET active_tick=2')
    c.e.store.record_metric(2, 'unemployment', 0.3)
    c.e.store.record_metric(2, 'resident_labor_force', 2)
    series = metric_series_for_display(c.e.store.conn, ['unemployment'])['unemployment']
    assert [point['tick'] for point in series] == [0, 1]


def test_legacy_series_shape_and_sparse_points_stay_unchanged(residence_case, monkeypatch):
    c = residence_case
    c.e.store.execute('UPDATE run_meta SET config_json=?', (json.dumps({'engine_semantics_version': 20}),))
    c.e.store.record_metric(0, 'unemployment', 0.3)
    c.e.store.record_metric(2, 'unemployment', 0.6)
    points = [{'tick': 0, 'value': 0.3}, {'tick': 2, 'value': 0.6}]
    assert metric_series_for_display(c.e.store.conn, ['unemployment', 'unknown']) == {'unemployment': points, 'unknown': []}
    reader = ReplayReader()
    monkeypatch.setattr(reader, '_conn', lambda _run: c.e.store.conn)
    assert reader.metrics('fixture', 'unemployment,unknown') == {'unemployment': points}
