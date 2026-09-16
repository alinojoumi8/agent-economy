"""A failed draft lifecycle batch cannot leave earlier people or bills changed."""
import pytest

from engine.population_history import ResidenceError

from .conftest import make_agent
from .test_population_commitments import local_services
from .test_population_movements import moving, advance
from .test_population_outside_life import outside_life, controlled_draw
from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case
from .test_semantics20_service_commitments import services, buy_insurance


def assert_unchanged(store, before):
    after = contents(store)
    assert sorted(name for name in before.keys() | after.keys()
                  if before.get(name) != after.get(name)) == []


def test_later_invalid_residence_rolls_back_registration_age_and_birth(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    newcomer, _ = make_agent(e, c.bank, 'New arrival', cash=0, region_id=1, arrived_tick=1)
    event = e.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1',
                           (c.heir,))
    e.store.update('events', event, payload_json='{}')
    monkeypatch.setitem(e.lifecycle.p, 'birth_annual_prob', 1.0)
    controlled_draw(monkeypatch, c, birth=0.0)
    births = []
    original = e.households.birth

    def observe_birth(*args, **kwargs):
        child = original(*args, **kwargs)
        assert e.store.scalar('SELECT COUNT(*) FROM person_lifecycle WHERE agent_id=?', (newcomer,)) == 1
        births.append(child)
        return child

    monkeypatch.setattr(e.households, 'birth', observe_birth)
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        e.lifecycle.run_nightly(1)
    assert len(births) == 1  # The failure occurs after real earlier-person effects.
    assert_unchanged(e.store, before)


def test_late_custody_failure_rolls_back_premium_and_birth_then_retry_settles_once(local_services, monkeypatch):
    s, e = local_services, local_services.e
    e.lifecycle.engine_semantics_version = 21
    policy = buy_insurance(s)
    monkeypatch.setattr(e.lifecycle, '_draw', lambda *_: 1.0)
    monkeypatch.setitem(e.households.p, 'scheduled_births', [{'tick': 2, 'parent_agent_id': s.client}])
    premiums_before = e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='insurance_premium'")
    original = e.project_rights.refresh
    attempted_children = []

    def fail_after_custody(tick):
        child = e.store.scalar('SELECT agent_id FROM person_lifecycle WHERE birth_key=?', (f'birth:2:{s.client}',))
        assert child is not None
        assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='insurance_premium'") == premiums_before + 1
        attempted_children.append(child)
        original(tick)
        raise RuntimeError('injected final custody refresh failure')

    monkeypatch.setattr(e.project_rights, 'refresh', fail_after_custody)
    before = contents(e.store)
    with pytest.raises(RuntimeError, match='final custody refresh failure'):
        e.lifecycle.run_nightly(2)
    assert len(attempted_children) == 1
    assert_unchanged(e.store, before)

    monkeypatch.setattr(e.project_rights, 'refresh', original)
    e.lifecycle.run_nightly(2)
    assert e.store.scalar('SELECT agent_id FROM person_lifecycle WHERE birth_key=?',
                         (f'birth:2:{s.client}',)) == attempted_children[0]
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='insurance_premium'") == premiums_before + 1
    assert e.store.scalar('SELECT next_premium_tick FROM insurance_policies WHERE id=?', (policy,)) == 4
    child = attempted_children[0]
    assert e.store.scalar('SELECT COUNT(*) FROM guardianships WHERE child_agent_id=? AND ended_tick IS NULL', (child,)) == 1
    assert e.ledger.balance(e.ledger.agent_checking_id(child)) == 0
    e.households.check_invariants(2)
    e.population.commitments.check_invariants()
    assert e.ledger.reconcile()[0]


def test_outside_beneficiary_keeps_multicurrency_inheritance_and_existing_identity(outside_life):
    c, e = outside_life, outside_life.e
    e.ledger.create_account('agent', c.person, 'fx', currency_code='EUR', opening_cents=37)
    movement = e.population.propose(0, c.heir, 'departure', [c.heir], 'heir-away', due_tick=1)['movement_id']
    advance(c, 1)
    assert e.population.settle(1, movement)['status'] == 'applied'
    e.households.record_census(1)
    assert not e.population.is_local(c.heir, 2)
    residence_before = [tuple(row) for row in e.store.query(
        'SELECT * FROM person_residence_events WHERE agent_id=? ORDER BY id', (c.heir,))]

    e.lifecycle.settle_death(2, c.person)
    estate = e.store.scalar('SELECT id FROM estate_cases WHERE deceased_agent_id=?', (c.person,))
    assert tuple(e.store.query_one('SELECT agent_id,weight,basis FROM estate_beneficiaries WHERE estate_id=?',
                                   (estate,))) == (c.heir, 1, 'social_tie')
    assert e.ledger.balance(c.heir_wallet) == 100
    assert e.store.scalar("SELECT balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=? "
                          "AND currency_code='EUR'", (c.heir,)) == 37
    assert e.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (c.heir,)) == c.heir_wallet
    assert not e.population.is_local(c.heir, 2)
    assert [tuple(row) for row in e.store.query(
        'SELECT * FROM person_residence_events WHERE agent_id=? ORDER BY id', (c.heir,))] == residence_before
    e.estate_cases.check_invariants()
    assert e.ledger.reconcile()[0]
    settled = contents(e.store)
    e.lifecycle.settle_death(2, c.person)
    assert_unchanged(e.store, settled)
