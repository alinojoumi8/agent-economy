"""Residence-bound economic cohorts, separate from retained financial ownership."""
from math import isfinite

from .position_history import cash_distribution_at, people_at, summarize_person_cash
from .population_history import ResidenceError, ResidenceHistory


def residence_cohorts_at(store, tick: int) -> dict[str, list[dict]]:
    """Reconstruct living cohorts at the selected day, validating every origin."""
    if type(tick) is not int or tick < 0:
        raise ValueError('tick must be a nonnegative integer')
    missing = store.query_one('SELECT a.id FROM agents a WHERE a.arrived_tick<=? AND NOT EXISTS '
        '(SELECT 1 FROM person_lifecycle p WHERE p.agent_id=a.id) LIMIT 1', (tick,))
    if missing:
        raise ResidenceError('known person lacks a registered lifecycle')
    history = ResidenceHistory(store)
    cohorts = {'resident': [], 'outside': []}
    for person in people_at(store, tick):
        residence = history.state_at(person['agent_id'], tick)
        if person['death_tick'] is None or person['death_tick'] > tick:
            cohorts[residence['state']].append(person)
    return cohorts


def cash_distributions_by_residence_at(store, tick: int) -> dict[str, dict]:
    """Keep all citizen wallets and partition them without moving any money."""
    cohorts = residence_cohorts_at(store, tick)
    return _cash_partitions(store, tick, cohorts)


def _cash_partitions(store, tick, cohorts):
    all_citizens = cash_distribution_at(store, tick)
    result = {'known_living': all_citizens, 'resident': {}, 'outside': {}}
    for name in ('resident', 'outside'):
        citizens = {p['agent_id'] for p in cohorts[name] if p['kind'] == 'citizen'}
        for currency, distribution in all_citizens.items():
            amounts = {person: amount for person, amount in distribution['person_cash_cents'].items()
                       if person in citizens}
            result[name][currency] = summarize_person_cash(amounts)
    return result


def current_population_metrics(economy, tick: int) -> dict[str, float]:
    """Current local activity stocks; historical readers consume stored metrics.

    Residence/cash readers are historical. Employment, retirement and sentiment
    here use current engine state, so they cannot backfill an earlier day.
    """
    store = economy.store
    meta = store.get_meta()
    current = meta['tick'] if meta['active_tick'] is None else meta['active_tick']
    if tick != current:
        raise ResidenceError('local economic snapshot requires the current engine boundary')
    cohorts = residence_cohorts_at(store, tick)
    resident_ids = {p['agent_id'] for p in cohorts['resident']}
    resident_citizens = {p['agent_id'] for p in cohorts['resident'] if p['kind'] == 'citizen'}
    agents = {row['id']: row for row in store.query('SELECT id,age,retired FROM agents ORDER BY id')}
    labor_force = {person for person in resident_citizens
                   if 18 <= agents[person]['age'] <= 64 and not agents[person]['retired']}
    workers = {row['agent_id'] for row in store.query("SELECT agent_id FROM employments WHERE status='active'")}
    control = economy.business_control
    workers.update(row['operator_id'] for row in store.query(
        f"SELECT {control.column} AS operator_id FROM {control.table} WHERE status<>'bankrupt'"))
    employed = len(labor_force & workers)
    sentiment = [float(row['value']) for row in store.query(
        "SELECT agent_id,value FROM beliefs WHERE key='sentiment' ORDER BY agent_id") if row['agent_id'] in resident_citizens]
    if not all(isfinite(value) for value in sentiment):
        raise ResidenceError('resident sentiment contains a nonfinite observation')
    insured = {row['agent_id'] for row in store.query("SELECT agent_id FROM insurance_policies WHERE status='active'")}
    values = {
        'resident_population': len(resident_ids),
        'known_living_outside': len(cohorts['outside']),
        'known_living_population': len(resident_ids) + len(cohorts['outside']),
        'resident_citizens': len(resident_citizens),
        'resident_labor_force': len(labor_force),
        'resident_working': employed,
        'resident_unemployed': len(labor_force) - employed,
        'resident_sentiment_observations': len(sentiment),
        'resident_insured': len(resident_ids & insured),
    }
    if labor_force:
        values['resident_unemployment'] = 1.0 - employed / len(labor_force)
        values['unemployment'] = values['resident_unemployment']
    if sentiment:
        values['resident_sentiment'] = sum(sentiment) / len(sentiment)
        values['sentiment'] = values['resident_sentiment']
    for name, currencies in _cash_partitions(store, tick, cohorts).items():
        if name == 'known_living':
            # Preserve the legacy all-citizen series from the same ledger pass.
            for currency, distribution in currencies.items():
                values[f'cash_gini:{currency}'] = distribution['gini']
                values[f'cash_population:{currency}'] = distribution['population_count']
            continue
        for currency, distribution in currencies.items():
            for metric, field in (
                ('cash_gini', 'gini'), ('cash_population', 'population_count'),
                ('cash_signed_cents', 'signed_cash_cents'),
                ('cash_nonnegative_cents', 'nonnegative_cash_cents'),
                ('cash_negative_cents', 'negative_cash_cents'),
            ):
                values[f'{name}_{metric}:{currency}'] = distribution[field]
    return values
