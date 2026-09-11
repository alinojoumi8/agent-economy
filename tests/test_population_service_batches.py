"""Draft service batches keep economic effects atomic and preserve return rules."""
import json

import pytest

from engine.population_history import ResidenceError
from .test_population_movements import moving, advance
from .test_population_residence_history import residence_case, contents
from .test_population_resident_services import resident_services, information, move_person
from .test_population_participation import participating
from .test_semantics20_estate_cases import estate_case


def unchanged(store, before):
    after = contents(store)
    assert sorted(name for name in before.keys() | after.keys()
                  if before.get(name) != after.get(name)) == []


def test_compute_activation_rolls_back_when_a_later_institution_has_invalid_history(resident_services):
    c, e = resident_services, resident_services.e
    bought = e.cognition.buy_compute_plan(0, c.person, 'flash')
    assert bought['ok']
    official = e.store.scalar('SELECT id FROM agents WHERE role IS NOT NULL ORDER BY id DESC LIMIT 1')
    event = e.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1', (official,))
    original_payload = e.store.scalar('SELECT payload_json FROM events WHERE id=?', (event,))
    e.store.update('events', event, payload_json='{}')
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        e.cognition.run_nightly(1)
    unchanged(e.store, before)

    e.store.update('events', event, payload_json=original_payload)
    e.cognition.run_nightly(1)
    assert e.cognition.current_subscription(c.person, 1)['id'] == bought['subscription_id']
    assert e.cognition.current_tier(c.person) == 'flash'
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='compute_subscription'") == 1
    settled = contents(e.store)
    e.cognition.run_nightly(1)
    unchanged(e.store, settled)
    assert e.ledger.reconcile()[0]


def test_public_compute_failure_rolls_back_all_charges_and_retry_bills_once(resident_services, monkeypatch):
    c, e = resident_services, resident_services.e
    before = contents(e.store)
    original = e.cognition._log_plan_change
    attempts = []

    def fail(tick, person, old_tier, new_tier, subscription, reason):
        result = original(tick, person, old_tier, new_tier, subscription, reason)
        if reason == 'institutional_renewal':
            attempts.append(person)
            if len(attempts) == 2:
                raise RuntimeError('injected second institutional receipt failure')
        return result

    with monkeypatch.context() as patch:
        patch.setattr(e.cognition, '_log_plan_change', fail)
        with pytest.raises(RuntimeError, match='second institutional receipt'):
            e.cognition.run_nightly(0)
    assert len(attempts) == 2
    unchanged(e.store, before)

    treasury_before = e.gov.treasury_balance()
    e.cognition.run_nightly(0)
    charge = e.store.scalar("SELECT SUM(price_cents) FROM compute_subscriptions WHERE payer_type='government' AND status='active'")
    assert charge > 0
    assert e.gov.treasury_balance() == treasury_before - charge
    settled = contents(e.store)
    e.cognition.run_nightly(0)
    unchanged(e.store, settled)
    e.population.commitments.check_invariants()
    assert e.ledger.reconcile()[0]


@pytest.mark.parametrize('operation', ['nightly', 'election'])
def test_fiscal_failure_cannot_repeat_benefits_or_shift_policy_twice(participating, monkeypatch, operation):
    c, e = participating, participating.e
    e.gov.p['election_interval_ticks'] = 1
    before = contents(e.store)
    tax, benefit = e.gov.tax_rate_bps(), e.gov.benefit_cents()
    balances = {wallet: e.ledger.balance(wallet) for wallet in (c.wallet, c.heir_wallet)}
    original = e.store.log_event

    def fail(tick, kind, *args, **kwargs):
        if kind == 'election_held':
            assert e.gov.tax_rate_bps() != tax
            raise RuntimeError('injected fiscal election receipt failure')
        return original(tick, kind, *args, **kwargs)

    run = e.gov.run_nightly if operation == 'nightly' else e.gov.hold_election
    with monkeypatch.context() as patch:
        patch.setattr(e.store, 'log_event', fail)
        with pytest.raises(RuntimeError, match='fiscal election receipt'):
            run(1)
    unchanged(e.store, before)
    run(1)
    assert e.gov.tax_rate_bps() == tax + e.gov.p['tax_step_bps']
    assert e.gov.benefit_cents() == benefit + e.gov.p['benefit_step_cents']
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='election_held'") == 1
    for wallet, balance in balances.items():
        assert e.ledger.balance(wallet) == balance + (benefit if operation == 'nightly' else 0)
    assert e.ledger.reconcile()[0]


def test_invalid_later_news_rolls_back_earlier_exposures_and_beliefs(resident_services, monkeypatch):
    c, e = resident_services, resident_services.e
    first_claim, first_item = information(c)
    claim = e.information.create_claim(0, c.heir, {'claim_key': 'later-news', 'predicate': 'supply', 'value': 3})
    assert claim['ok']
    item = e.information.publish_item(0, c.heir, {'claim_id': claim['claim_id'], 'item_type': 'social_post', 'body': 'Later supply'})
    assert item['ok'] and item['virality'] == 1.0
    e.store.update('claims', claim['claim_id'], value_json='invalid-json')
    seen = []
    original = e.information._update_beliefs

    def observe(tick, person, observed_item, perceived, exposure):
        result = original(tick, person, observed_item, perceived, exposure)
        seen.append((person, observed_item['id']))
        return result

    monkeypatch.setattr(e.information, '_update_beliefs', observe)
    before = contents(e.store)
    with pytest.raises(json.JSONDecodeError):
        e.information.run_nightly(1)
    assert (c.person, first_item) in seen
    unchanged(e.store, before)

    e.store.update('claims', claim['claim_id'], value_json='3')
    e.information.run_nightly(1)
    for claim_id, item_id in ((first_claim, first_item), (claim['claim_id'], item['item_id'])):
        assert e.store.scalar('SELECT COUNT(*) FROM information_exposures WHERE agent_id=? AND item_id=?', (c.person, item_id)) == 1
        assert e.store.scalar('SELECT COUNT(*) FROM beliefs WHERE agent_id=? AND key=?', (c.person, f'claim:{claim_id}')) == 1
    settled = contents(e.store)
    e.information.run_nightly(1)
    unchanged(e.store, settled)


def test_return_does_not_restore_an_active_paid_plan_without_a_new_purchase(resident_services):
    c, e = resident_services, resident_services.e
    bought = e.cognition.buy_compute_plan(0, c.person, 'flash')
    assert bought['ok']
    advance(c, 1)
    e.cognition.run_nightly(1)
    assert e.cognition.current_tier(c.person) == 'flash'
    paid_balance = e.ledger.balance(c.wallet)
    move_person(c, c.person, tick=1, due=2)
    e.cognition.run_nightly(2)
    assert e.cognition.current_tier(c.person) == 'local'
    assert e.cognition.current_subscription(c.person, 2) is None

    returned = e.population.propose(2, c.person, 'return', [c.person], 'back', due_tick=3, destination_region_id=1)['movement_id']
    advance(c, 3)
    assert e.population.settle(3, returned)['status'] == 'applied'
    e.cognition.run_nightly(3)
    assert e.cognition.current_tier(c.person) == 'local'
    assert e.cognition.current_subscription(c.person, 3) is None
    assert e.ledger.balance(c.wallet) == paid_balance
    assert e.store.scalar('SELECT status FROM compute_subscriptions WHERE id=?', (bought['subscription_id'],)) == 'cancelled'
    renewed = e.cognition.buy_compute_plan(3, c.person, 'flash')
    assert renewed['ok'] and renewed['subscription_id'] != bought['subscription_id']
    e.cognition.run_nightly(4)
    assert e.cognition.current_subscription(c.person, 4)['id'] == renewed['subscription_id']
    assert e.cognition.current_tier(c.person) == 'flash'
    assert e.ledger.balance(c.wallet) == paid_balance - e.cognition._plan_cost('flash')
    e.population.commitments.check_invariants()
    assert e.ledger.reconcile()[0]
