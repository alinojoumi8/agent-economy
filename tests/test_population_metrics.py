"""Resident activity and retained outside cash through real metric snapshots."""
import asyncio
import json
import sqlite3

import pytest

from engine.population_history import ResidenceError
from engine.population_statistics import cash_distributions_by_residence_at, residence_cohorts_at
from engine.position_history import cash_distribution_at
from research.metric_registry import metric_catalog, metric_definition, read_metric_observation
from world.metrics import Metrics

from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case
from .test_population_scenario import proposal, scenario_world
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_actions import assert_closed_replay


def boundary(c, tick):
    config = {**c.e.config, 'engine_semantics_version': 21}
    c.e.store.execute('UPDATE run_meta SET tick=?,active_tick=NULL,config_json=?', (tick, json.dumps(config)))


def depart(c, person, tick=1):
    previous = c.history.state_at(person, tick)['id']
    return c.history.transition(tick, person, 'departure', previous_id=previous, request_key=f'out-{person}')


def test_departed_owner_does_not_count_as_a_local_worker_or_sentiment(residence_case):
    c = residence_case
    c.e.store.execute('UPDATE agents SET age=30,retired=0')
    c.e.firms.found_firm(0, c.person, 'Retained business', 'manufacturing', shares=100)
    c.e.store.execute("INSERT INTO beliefs(agent_id,key,value,updated_tick) VALUES(?,'sentiment',0.9,0),(?,'sentiment',-0.2,0)", (c.person, c.heir))
    before = Metrics(c.e, semantics_version=20).snapshot(0)
    assert before['unemployment'] == 0.5
    depart(c, c.person)
    boundary(c, 1)
    ledger = [tuple(row) for row in c.e.store.query('SELECT * FROM ledger_entries ORDER BY id')]
    now = Metrics(c.e, semantics_version=21).snapshot(1)
    assert now['resident_population'] == now['known_living_outside'] == 1
    assert now['known_living_population'] == 2
    assert now['resident_labor_force'] == now['resident_unemployed'] == 1
    assert now['resident_working'] == 0 and now['unemployment'] == 1
    assert now['sentiment'] == now['resident_sentiment'] == -0.2
    assert now['cash_population:USD'] == 2
    assert now['resident_cash_population:USD'] == now['outside_cash_population:USD'] == 1
    assert now['money_supply'] == before['money_supply']
    assert ledger == [tuple(row) for row in c.e.store.query('SELECT * FROM ledger_entries ORDER BY id')]
    assert c.e.ledger.reconcile()[0]
    assert read_metric_observation(c.e.store, 'unemployment', 1)['definition']['version'] == 'resident-unemployment-v21'
    assert metric_definition('unemployment', semantics_version=20).version == 'unique-worker-share-v7'


def test_empty_resident_cohort_is_unavailable_for_rates_and_keeps_outside_cash(residence_case):
    c = residence_case
    for person in (c.person, c.heir):
        depart(c, person)
    boundary(c, 1)
    metrics = Metrics(c.e, semantics_version=21)
    out = metrics.snapshot(1)
    assert out['resident_population'] == out['resident_labor_force'] == 0
    assert out['known_living_outside'] == 2
    assert out['outside_cash_signed_cents:USD'] == 100
    assert 'unemployment' not in out and 'sentiment' not in out
    for name in ('unemployment', 'resident_unemployment'):
        observation = read_metric_observation(c.e.store, name, 1)
        assert observation['value'] is None and observation['reason'] == 'empty_resident_labor_force'
    assert read_metric_observation(c.e.store, 'sentiment', 1)['reason'] == 'no_resident_sentiment_observations'
    assert read_metric_observation(c.e.store, 'resident_cash_gini:USD', 1)['value'] == 0
    before = contents(c.e.store)
    assert metrics.snapshot(1) == out
    assert contents(c.e.store) == before


@pytest.mark.parametrize('owner_age,owner_retired,heir_age,force,working', [
    (17, 0, 64, 1, 0), (64, 0, 65, 1, 1), (30, 1, 17, 0, 0),
])
def test_labor_eligibility_keeps_minors_and_retirees_in_resident_cash(
        residence_case, owner_age, owner_retired, heir_age, force, working):
    c = residence_case
    c.e.store.execute('UPDATE agents SET age=?,retired=? WHERE id=?', (owner_age, owner_retired, c.person))
    c.e.store.execute('UPDATE agents SET age=?,retired=0 WHERE id=?', (heir_age, c.heir))
    c.e.firms.found_firm(0, c.person, 'Owned capital', 'manufacturing', shares=100)
    out = Metrics(c.e, semantics_version=21).snapshot(0)
    assert out['resident_population'] == out['resident_cash_population:USD'] == 2
    assert out['resident_labor_force'] == force and out['resident_working'] == working
    assert out['resident_unemployed'] == force - working
    assert ('unemployment' in out) == bool(force)


def test_retry_removes_rates_whose_observation_cohort_became_empty(residence_case):
    c = residence_case
    c.e.store.execute('UPDATE agents SET age=30,retired=0')
    c.e.store.execute("INSERT INTO beliefs(agent_id,key,value,updated_tick) VALUES(?,'sentiment',0.5,0)", (c.person,))
    metrics = Metrics(c.e, semantics_version=21)
    assert metrics.snapshot(0)['sentiment'] == 0.5
    c.e.store.execute('UPDATE agents SET retired=1')
    c.e.store.execute("DELETE FROM beliefs WHERE key='sentiment'")
    out = metrics.snapshot(0)
    for key in ('unemployment', 'resident_unemployment', 'sentiment', 'resident_sentiment'):
        assert key not in out
        assert not c.e.store.scalar('SELECT 1 FROM metrics WHERE tick=0 AND name=?', (key,))
    before = contents(c.e.store)
    assert metrics.snapshot(0) == out and contents(c.e.store) == before


@pytest.mark.parametrize('denominator', [-1, 0.5, float('inf'), 'invalid', None])
def test_strict_resident_rate_reader_refuses_invalid_or_missing_counts(residence_case, denominator):
    c = residence_case
    c.e.store.execute('UPDATE agents SET age=30,retired=0')
    boundary(c, 0)
    Metrics(c.e, semantics_version=21).snapshot(0)
    if denominator is None:
        c.e.store.execute("DELETE FROM metrics WHERE name='resident_labor_force'")
    else:
        c.e.store.execute("UPDATE metrics SET value=? WHERE name='resident_labor_force'", (denominator,))
    before = contents(c.e.store)
    observation = read_metric_observation(c.e.store, 'unemployment', 0)
    assert observation['value'] is None
    assert observation['reason'] == ('resident_denominator_not_recorded' if denominator is None else 'invalid_resident_denominator')
    future = read_metric_observation(c.e.store, 'unemployment', 1)
    assert future['reason'] == 'future_tick'
    assert future['definition']['version'] == 'resident-unemployment-v21'
    assert contents(c.e.store) == before


def test_study_outcomes_bind_residence_semantics_without_relabeling_legacy(monkeypatch):
    from engine import semantics
    from research.price_catalog import draft_price_study
    from research.studies import StudySpec
    from run_config import load_config

    config = load_config('runs/price-lab-pilot.yaml')
    config['engine_semantics_version'] = 20
    raw = draft_price_study(config, 'G2', seeds=[1, 2], horizon=3, intervention_tick=2).model_dump(mode='json')
    raw['analysis']['outcomes'].append(dict(key='local_jobs', metric='unemployment',
        metric_version='unique-worker-share-v7', aggregation='terminal', currency=None, purpose='exploratory'))
    assert StudySpec.model_validate(raw).model.engine_semantics_version == 20
    raw['model']['engine_semantics_version'] = 21
    with pytest.raises(ValueError, match='unsupported'):
        StudySpec.model_validate(raw)
    # Private draft contract validation only; public admission remains unchanged.
    monkeypatch.setattr(semantics, 'CURRENT_ENGINE_SEMANTICS_VERSION', 21)
    with pytest.raises(ValueError, match='unknown metric/version'):
        StudySpec.model_validate(raw)
    raw['analysis']['outcomes'][-1]['metric_version'] = 'resident-unemployment-v21'
    assert StudySpec.model_validate(raw).analysis.outcomes[-1].metric_version == 'resident-unemployment-v21'
    for version, expected in ((20, 'unique-worker-share-v7'), (21, 'resident-unemployment-v21')):
        definitions = metric_catalog(semantics_version=version)['definitions']
        assert len({item['key'] for item in definitions}) == len(definitions)
        assert next(item for item in definitions if item['key'] == 'unemployment')['version'] == expected
        assert any(item['key'] == 'resident_population' for item in definitions) == (version == 21)


def test_cash_partitions_are_historical_currency_separate_and_reconcile(residence_case):
    c = residence_case
    c.e.ledger.create_account('agent', c.person, 'fx', currency_code='EUR', opening_cents=37, tick=0)
    c.e.ledger.create_account('agent', c.person, 'wage_receivable', opening_cents=900, tick=0)
    departure = depart(c, c.person)
    c.e.ledger.transfer(1, c.wallet, c.heir_wallet, 150)
    c.history.transition(2, c.person, 'return', previous_id=departure, request_key='back')
    c.e.ledger.create_account('agent', c.heir, 'fx', currency_code='CAD', opening_cents=29, tick=3)
    c.e.lifecycle.settle_death(3, c.person)
    boundary(c, 3)
    before = contents(c.e.store)
    for tick in (0, 1, 2, 3):
        groups = cash_distributions_by_residence_at(c.e.store, tick)
        assert groups['known_living'] == cash_distribution_at(c.e.store, tick)
        for currency, all_people in groups['known_living'].items():
            for key in ('population_count', 'signed_cash_cents', 'negative_cash_cents', 'nonnegative_cash_cents'):
                assert all_people[key] == sum(groups[name][currency][key] for name in ('resident', 'outside'))
    out = cash_distributions_by_residence_at(c.e.store, 1)
    assert set(out['outside']) == {'EUR', 'USD'}
    assert out['outside']['EUR']['signed_cash_cents'] == 37
    assert out['outside']['USD']['signed_cash_cents'] == -50
    assert out['outside']['USD']['gini'] == 0
    assert out['resident']['USD']['signed_cash_cents'] == 150
    assert out['outside']['USD']['person_cash_cents'] == {c.person: -50}
    assert cash_distributions_by_residence_at(c.e.store, 0)['resident']['USD']['person_cash_cents'][c.person] == 100
    assert c.person not in {person['agent_id'] for person in residence_cohorts_at(c.e.store, 3)['resident']}
    assert contents(c.e.store) == before
    assert c.e.ledger.reconcile()[0]


def test_invalid_history_prevents_any_snapshot_side_effect(residence_case):
    c = residence_case
    origin_event = c.history.state_at(c.heir, 0)['event_id']
    c.e.store.execute("UPDATE events SET payload_json='{}' WHERE id=?", (origin_event,))
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        Metrics(c.e, semantics_version=21).snapshot(0)
    assert contents(c.e.store) == before


def test_late_metric_write_failure_rolls_back_cpi_index_and_all_metrics(residence_case):
    c = residence_case
    firm = c.e.firms.found_firm(0, c.person, 'Snapshot basket', 'manufacturing',
                              product={'unit_price_cents': 80}, shares=100)
    c.e.store.execute("UPDATE firms SET status='listed' WHERE id=?", (firm,))
    # Declared price fixture for the legacy index initializer; not a trade.
    c.e.store.record_metric(0, f'stock:{firm}', 500)
    assert not c.e.store.scalar("SELECT 1 FROM metrics WHERE name IN ('cpi_base','index_divisor')")
    c.e.store.execute("CREATE TEMP TRIGGER reject_population_metric BEFORE INSERT ON metrics "
        "WHEN NEW.name='resident_population' BEGIN SELECT RAISE(ABORT,'injected metric failure'); END")
    before = contents(c.e.store)
    metrics = Metrics(c.e, semantics_version=21)
    with pytest.raises(sqlite3.IntegrityError, match='injected metric failure'):
        metrics.snapshot(0)
    assert contents(c.e.store) == before
    c.e.store.execute('DROP TRIGGER reject_population_metric')
    out = metrics.snapshot(0)
    assert out['cpi'] == out['index'] == 100
    assert c.e.store.scalar("SELECT value FROM metrics WHERE name='cpi_base'") == 80
    assert c.e.store.scalar("SELECT value FROM metrics WHERE name='index_divisor'") == 5
    before = contents(c.e.store)
    assert metrics.snapshot(0) == out and contents(c.e.store) == before


@pytest.mark.parametrize('active', [False, True])
def test_current_activity_statistics_cannot_rewrite_historical_days(residence_case, active):
    c = residence_case
    boundary(c, 1 if active else 2)
    if active:
        c.e.store.execute('UPDATE run_meta SET active_tick=2')
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match='current engine boundary'):
        Metrics(c.e, semantics_version=21).snapshot(1)
    assert contents(c.e.store) == before


def test_duplicate_current_metric_rows_reject_the_whole_snapshot(residence_case):
    c = residence_case
    for _ in range(2):
        c.e.store.record_metric(0, 'resident_population', 2)
    before = contents(c.e.store)
    with pytest.raises(ValueError, match='duplicate current metric'):
        Metrics(c.e, semantics_version=21).snapshot(0)
    assert contents(c.e.store) == before


def test_world_resident_metrics_restart_and_replay_with_retained_outside_cash(scenario_world):
    entries = [proposal(), proposal(key='back', tick=3, due=5, cause='return')]
    world = scenario_world(entries, 'metrics-source', config_overrides=RUNTIME_CONFIG)
    for _ in range(2):
        asyncio.run(world.step())
    assert read_metric_observation(world.store, 'known_living_outside', 2)['value'] == 1
    asyncio.run(world.step(pause_after_phase='MORNING'))
    scenario_world.close(world)
    world = scenario_world(entries, 'metrics-source', config_overrides=RUNTIME_CONFIG)
    asyncio.run(world.step())
    for _ in range(3):
        asyncio.run(world.step())
    for day in range(1, 7):
        census = world.store.query_one('SELECT * FROM population_resident_census WHERE tick=?', (day,))
        assert read_metric_observation(world.store, 'resident_population', day)['value'] == census['closing_residents']
        assert read_metric_observation(world.store, 'known_living_outside', day)['value'] == census['known_living_outside']
    assert read_metric_observation(world.store, 'outside_cash_population:NSD', 3)['value'] == 1
    assert_closed_replay(scenario_world, world, RUNTIME_CONFIG, 6, entries=entries)
