"""Adding residence contracts must not relabel saved legacy observations."""
import json
from pathlib import Path

import pytest

from research.metric_registry import metric_catalog, read_metric_observation


def test_semantics20_catalog_matches_the_preserved_v2_catalog():
    frozen = json.loads((Path(__file__).parent/'fixtures/metric_registry_v2.json').read_text(encoding='utf-8'))
    current = json.loads(json.dumps(metric_catalog(semantics_version=20)))
    assert current == frozen['catalog']
    assert metric_catalog()['registry_version'] == 'research-metrics-v3'
    assert metric_catalog(semantics_version=21)['registry_version'] == 'research-metrics-v3'


@pytest.mark.parametrize('semantics', [1, 7, 20, 21])
def test_available_missing_future_and_unknown_observations_keep_the_run_registry(store, semantics):
    store.set_meta(tick=2, config_json=json.dumps({'engine_semantics_version': semantics}))
    store.record_metric(1, 'policy_rate', 125)
    expected = 'research-metrics-v3' if semantics == 21 else 'research-metrics-v2'
    before = store.conn.total_changes
    for name, tick, reason in [('policy_rate', 1, None), ('policy_rate', 2, 'not_recorded_at_tick'),
                               ('policy_rate', 3, 'future_tick'), ('unknown_metric', 1, 'unregistered_metric')]:
        result = read_metric_observation(store, name, tick)
        assert result['registry_version'] == expected
        assert result['reason'] == reason
        assert result['value'] == (125 if reason is None else None)
    assert store.conn.total_changes == before
