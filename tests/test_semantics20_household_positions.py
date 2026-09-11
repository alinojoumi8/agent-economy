"""Historical household instruments, conditional estates and currency cash Gini."""
import json

import pytest

from engine.credit import LoanTerms
from engine.ledger import SYS_EXTERNAL, SYS_COMMODITY
from engine.position_history import account_balances_at, cash_distribution_at
from research.hashing import canonical_hashes
from research.household_positions import household_positions
from research.metric_registry import metric_definition, read_metric_observation
from world.metrics import Metrics

from .conftest import make_agent
from .test_semantics19_estate_cash import foreign_bank, spent_loan
from .test_semantics20_estate_cases import estate_case, validate
from .test_semantics20_legal_awards import award_case, claim, decide
from .test_semantics20_wage_awards import fund, file_wages, verify
from .test_semantics20_estate_securities import indebted_security_estate
from .test_semantics20_project_rights import property_world, join_household
from .test_semantics13_construction import _advance_to_building


def committed(e, tick):
    # The mechanics fixtures declare an end-of-tick boundary explicitly.
    e.store.execute("UPDATE run_meta SET tick=?,active_tick=NULL", (tick,))


def instruments(report):
    return {row["key"]: row for row in report["instruments"]}


def home(report, person):
    return next(row for row in report["households"] if person in row["members"])


def estate(report, person):
    return next(row for row in report["estates"] if row["nominee_agent_id"] == person)


def wage_case(c, *, daily=150, tax=2000):
    # The older payroll-only helper inserts an employer without an issued cap
    # table. Positions instead need an actual company and its issuance history.
    c.firm = c.e.firms.found_firm(0, c.person, "Recorded employer", "manufacturing", shares=100)
    c.firm_wallet = c.e.firms.get(c.firm)["account_id"]
    c.employment = c.e.store.insert("employments", agent_id=c.creditor, firm_id=c.firm,
        wage_cents=daily * 30, pay_interval_ticks=30, start_tick=0, next_pay_tick=1, status="active")
    c.e.store.update("agents", c.creditor, employer_id=c.firm)
    c.e.store.record_metric(0, "tax_rate_bps", tax)
    c.e.daily_time.prepare_day(1)
    c.wage_claim = c.e.store.scalar("SELECT id FROM wage_claims WHERE employment_id=?", (c.employment,))
    assert c.wage_claim is not None
    return c


def test_cash_history_excludes_claims_restricted_cash_and_future_people_or_currencies(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    e.ledger.create_account("agent", heir, "wage_receivable", opening_cents=900, tick=0)
    e.ledger.create_account("agent", heir, "legal_escrow", opening_cents=500, tick=0)
    euro = e.ledger.create_account("agent", heir, "fx", currency_code="EUR", opening_cents=300, tick=2)
    future, future_wallet = make_agent(e, bank, "Arrival", cash=0, region_id=1, arrived_tick=3)
    e.households.register_person(3, future, "arrival")
    e.ledger.transfer(3, e.ledger.system_account(SYS_EXTERNAL), future_wallet, 100)
    e.ledger.transfer(3, wallet, heir_wallet, 50)
    committed(e, 3)
    assert cash_distribution_at(e.store, 0) == {"USD": {
        "gini": 0.5, "population_count": 2, "nonnegative_cash_cents": 100,
        "signed_cash_cents": 100, "negative_cash_cents": 0, "person_cash_cents": {person: 100, heir: 0}}}
    later = cash_distribution_at(e.store, 3)
    assert later["USD"]["gini"] == pytest.approx(1 / 6)
    assert later["EUR"]["gini"] == pytest.approx(2 / 3)
    assert later["EUR"]["person_cash_cents"] == {person: 0, heir: 300, future: 0}
    old = {r["id"]: r for r in account_balances_at(e.store, 0)}
    assert old[wallet]["amount_cents"] == 100 and euro not in old and future_wallet not in old


def test_cash_nets_only_same_person_currency_then_clips_and_keeps_empty_population_explicit(estate_case):
    e, bank, person, wallet, heir, _ = estate_case
    e.ledger.create_account("agent", person, "savings", opening_cents=30, tick=0)
    e.ledger.transfer(1, wallet, e.ledger.system_account(SYS_EXTERNAL), 150)
    dist = cash_distribution_at(e.store, 1)["USD"]
    assert dist["signed_cash_cents"] == dist["negative_cash_cents"] == -20
    assert dist["gini"] == dist["nonnegative_cash_cents"] == 0
    # An empty population is distinct from inequality in an observed cohort.
    e.lifecycle.settle_death(2, person)
    e.lifecycle.settle_death(3, heir)
    assert cash_distribution_at(e.store, 3)["USD"]["population_count"] == 0
    assert cash_distribution_at(e.store, 3)["USD"]["gini"] == 0
    assert cash_distribution_at(e.store, 0)["USD"]["person_cash_cents"][person] == 130


def test_metric_emission_is_versioned_and_legacy_values_and_registry_stay_explicit(estate_case):
    e, _, person, _, heir, _ = estate_case
    e.ledger.create_account("agent", heir, "wage_receivable", opening_cents=100, tick=0)
    committed(e, 0)
    legacy = Metrics(e, semantics_version=19).snapshot(0)
    assert legacy["gini"] == 0 and "cash_gini:USD" not in legacy
    current = Metrics(e, semantics_version=20).snapshot(0)
    assert current["gini"] == 0 and current["cash_gini:USD"] == 0.5
    assert current["cash_population:USD"] == 2
    value = read_metric_observation(e.store, "cash_gini:USD", 0)
    assert (value["value"], value["currency"], value["definition"]["version"]) == (0.5, "USD", "citizen-wallet-cash-gini-v20")
    assert read_metric_observation(e.store, "gini", 0)["definition"]["label"].startswith("Legacy")
    assert metric_definition("cash_gini:usd") is None
    assert read_metric_observation(e.store, "cash_gini:EUR", 0)["reason"] == "currency_not_observed_at_tick"
    assert read_metric_observation(e.store, "cash_gini:USD", 1)["reason"] == "future_tick"
    e.store.execute("UPDATE run_meta SET active_tick=0")
    assert read_metric_observation(e.store, "cash_gini:USD", 0)["reason"] == "uncommitted_tick"


@pytest.mark.parametrize("tick", [-1, True, 0.5, "0"])
def test_position_reader_rejects_invalid_time_without_mutation(estate_case, tick):
    e, *_ = estate_case
    before = canonical_hashes(e.store)
    with pytest.raises(ValueError):
        household_positions(e.store, tick=tick)
    assert canonical_hashes(e.store) == before


def test_reader_requires_supported_committed_semantics(estate_case):
    e, *_ = estate_case
    with pytest.raises(ValueError, match="committed"):
        household_positions(e.store, tick=1)
    e.store.execute("UPDATE run_meta SET active_tick=0")
    with pytest.raises(ValueError, match="committed"):
        household_positions(e.store, tick=0)
    e.store.execute("UPDATE run_meta SET active_tick=NULL,config_json=?", (json.dumps({"engine_semantics_version": 19}),))
    with pytest.raises(ValueError, match="Semantics 20"):
        household_positions(e.store, tick=0)
    assert read_metric_observation(e.store, "cash_gini:USD", 0)["reason"] == "incompatible_metric_semantics"


def test_personal_principal_history_excludes_interest_and_later_default(estate_case):
    e, bank, person, wallet, _, _ = estate_case
    loan = e.bank.disburse_loan(0, bank, "agent", person, LoanTerms(10_000, 1200, 60, 30))
    e.bank.process_due_loans(30)
    remaining = e.store.scalar("SELECT outstanding_cents FROM loans WHERE id=?", (loan,))
    assert 0 < remaining < 10_000
    e.ledger.transfer(31, wallet, e.ledger.system_account(SYS_COMMODITY), e.ledger.balance(wallet))
    for tick in (60, 90, 120):
        e.bank.process_due_loans(tick)
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "default"
    committed(e, 120)
    amounts = [instruments(household_positions(e.store, tick=t))[f"loan:{loan}"]["face_cents"] for t in (0, 30, 119, 120)]
    assert amounts == [10_000, remaining, remaining, 0]
    assert f"loan:{loan}" in home(household_positions(e.store, tick=30), person)["debt_keys"]


def test_two_heirs_reference_one_nominee_wage_claim_with_exact_conditional_fractions(award_case):
    c = wage_case(award_case, daily=300)
    partnership = c.e.families.propose(0, c.creditor, "partnership", "heirs", partner_id=c.heir)["household_decision_id"]
    c.e.families.respond(0, c.heir, partnership, "accept")
    child = c.e.households.birth(1, c.creditor)
    c.e.lifecycle.settle_death(2, c.creditor)
    committed(c.e, 2)
    before = canonical_hashes(c.e.store)
    report = household_positions(c.e.store, tick=2)
    position = instruments(report)[f"wage:{c.wage_claim}"]
    pool = estate(report, c.creditor)
    assert position["face_cents"] == 300 and position["holder"]["id"] == pool["estate_id"]
    assert pool["asset_keys"].count(position["key"]) == 1
    assert pool["by_currency"]["USD"]["receivable_face_cents"] == 300
    interests = [r for h in report["households"] for r in h["contingent_interests"] if r["origin_estate_id"] == pool["estate_id"]]
    assert {r["beneficiary_agent_id"] for r in interests} == {c.heir, child}
    assert all(r["fraction_if_intervening_claims_settled"] == {"numerator": "1", "denominator": "2"} for r in interests)
    assert all(r["amount_cents"] is None for r in interests)
    assert all(position["key"] not in h["asset_keys"] for h in report["households"])
    assert report["net_wealth_cents"] is None and canonical_hashes(c.e.store) == before
    verify(c)


def test_successive_estates_keep_each_creditor_boundary_and_actual_collection(award_case):
    c = wage_case(award_case, daily=300, tax=0)
    # The initial worker and its recorded heir each owe an independent bank principal.
    first_loan = spent_loan(c.e, c.bank, c.creditor, c.creditor_wallet, 100)
    second_loan = spent_loan(c.e, c.bank, c.heir, c.heir_wallet, 50)
    survivor, survivor_wallet = make_agent(c.e, c.bank, "Successor", cash=0, region_id=1)
    c.e.households.register_person(0, survivor, "genesis")
    c.e.store.insert("social_ties", agent_a=c.heir, agent_b=survivor, weight=10)
    c.e.lifecycle.settle_death(2, c.creditor)
    c.e.lifecycle.settle_death(3, c.heir)
    committed(c.e, 3)
    report = household_positions(c.e.store, tick=3)
    first, second = estate(report, c.creditor), estate(report, c.heir)
    assert first["creditors_in_priority_order"][0]["instrument_key"] == f"loan:{first_loan}"
    assert second["creditors_in_priority_order"][0]["instrument_key"] == f"loan:{second_loan}"
    path = next(r for r in home(report, survivor)["contingent_interests"] if r["origin_estate_id"] == first["estate_id"])
    assert path["estate_path"] == [first["estate_id"], second["estate_id"]] and path["amount_cents"] is None
    fund(c, 300, tick=4)
    assert c.e.earned_wages.settle(4, c.wage_claim) == 300
    assert c.e.ledger.balance(survivor_wallet) == 150
    committed(c.e, 4)
    after = household_positions(c.e.store, tick=4)
    assert all(not e["creditors_in_priority_order"] for e in after["estates"])
    assert home(after, survivor)["by_currency"]["USD"]["wallet_cash_cents"] == 150
    assert household_positions(c.e.store, tick=3) == report
    verify(c)


def test_wage_novation_partial_collection_and_loss_count_the_underlying_right_once(award_case):
    c = wage_case(award_case)
    fund(c, 50)
    c.e.earned_wages.settle(1, c.wage_claim)
    matter, evidence = file_wages(c)
    outcome = decide(c, matter, evidence, 120, tick=2)
    assert outcome["ok"], outcome
    award = outcome["enforcement"]["award_id"]
    fund(c, 20, tick=3)
    c.e.earned_wages.process_due(3)
    c.e.firms.bankrupt_firm(4, c.firm)
    committed(c.e, 4)
    for tick, wages, award_face in ((1, 100, None), (2, 0, 70), (3, 0, 50), (4, 0, 0)):
        report = household_positions(c.e.store, tick=tick)
        rows = instruments(report)
        assert rows[f"wage:{c.wage_claim}"]["face_cents"] == wages
        if award_face is None:
            assert f"award:{award}" not in rows
        else:
            assert rows[f"award:{award}"]["face_cents"] == award_face
            assert rows[f"award:{award}"]["replaces"] == [f"wage:{c.wage_claim}"]
        assert home(report, c.creditor)["by_currency"]["USD"]["receivable_face_cents"] == wages + (award_face or 0)
    verify(c)


def test_contract_judgment_replacement_and_escrow_have_distinct_positions(award_case):
    c = award_case
    matter, evidence = claim(c, 150)
    obligation = c.e.store.scalar("SELECT id FROM obligations")
    c.e.lifecycle.settle_death(2, c.person)
    result = decide(c, matter, evidence, 120, tick=3)
    assert result["ok"], result
    award = result["enforcement"]["award_id"]
    committed(c.e, 3)
    before = household_positions(c.e.store, tick=2)
    pool = estate(before, c.person)
    assert pool["by_currency"]["USD"]["restricted_cash_cents"] == 100
    assert pool["by_currency"]["USD"]["debt_face_cents"] == 150
    assert pool["reserves_are_admitted_debts"] is False
    assert pool["unresolved_reserves"][0]["protected_obligations"] == [{"obligation_id": obligation, "protected_cents": 150}]
    after = household_positions(c.e.store, tick=3)
    rows = instruments(after)
    assert rows[f"obligation:{obligation}"]["face_cents"] == 0
    assert rows[f"award:{award}"]["face_cents"] == 20
    assert rows[f"award:{award}"]["replaces"] == [f"obligation:{obligation}"]
    assert home(after, c.creditor)["by_currency"]["USD"]["receivable_face_cents"] == 20


def test_membership_and_death_move_references_only_at_the_recorded_boundary(estate_case):
    e, _, person, _, heir, _ = estate_case
    join_household(e, heir, person, 1)
    e.lifecycle.settle_death(2, person)
    committed(e, 2)
    zero, one, two = [household_positions(e.store, tick=t) for t in range(3)]
    assert len(zero["households"]) == 2
    assert home(one, person)["members"] == [person, heir]
    assert home(one, person)["by_currency"]["USD"]["wallet_cash_cents"] == 100
    assert home(two, heir)["members"] == [heir]
    assert home(two, heir)["by_currency"]["USD"]["wallet_cash_cents"] == 100
    assert zero["estates"] == one["estates"] == []
    validate(e)


def test_foreign_estate_principal_is_not_netted_against_domestic_cash(estate_case):
    e, _, person, wallet, heir, _ = estate_case
    bank = foreign_bank(e, "EUR")
    euro = e.ledger.create_account("agent", person, "fx", bank_id=bank, currency_code="EUR")
    loan = spent_loan(e, bank, person, euro, 70)
    e.lifecycle.settle_death(1, person)
    committed(e, 1)
    report = household_positions(e.store, tick=1)
    assert instruments(report)[f"loan:{loan}"]["face_cents"] == 70
    assert estate(report, person)["by_currency"]["EUR"]["debt_face_cents"] == 70
    assert home(report, heir)["by_currency"]["USD"]["wallet_cash_cents"] == 100
    assert report["currency_conversion"] is None


def test_security_marks_require_an_execution_and_keep_its_date_after_the_sale(estate_case):
    e, _, person, _, heir, _, loan, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    from engine.actions import ActionExecutor
    actions = ActionExecutor(e)
    for actor, side in ((heir, "sell"), (buyer, "buy")):
        result = actions.execute_action(2, actor, {"type": "place_order", "firm_id": firm, "side": side,
            "qty": 10, "limit_price": 20, **({"estate_id": estate_id} if side == "sell" else {})})
        assert result["ok"], result
    assert len(e.exchange.match_firm(2, firm)) == 1
    committed(e, 3)
    old = instruments(household_positions(e.store, tick=1))[f"shares:{firm}:agent:{person}"]
    assert old["quantity"] == "10" and old["mark"] is None
    report = household_positions(e.store, tick=3)
    rows = instruments(report)
    assert f"shares:{firm}:agent:{person}" not in rows
    mark = rows[f"shares:{firm}:agent:{buyer}"]["mark"]
    assert (mark["amount_cents"], mark["observed_tick"], mark["age_ticks"]) == (200, 2, 1)
    assert rows[f"loan:{loan}"]["face_cents"] == 0
    assert home(report, buyer)["by_currency"]["USD"]["observed_equity_marks_cents"] == 200
    validate(e)


def test_property_rights_keep_history_and_exact_fraction_without_a_cost_valuation(property_world):
    world, owner, heir = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    e.lifecycle.settle_death(5, owner["id"])
    committed(e, 5)
    before = instruments(household_positions(e.store, tick=4))[f"property:{project}:agent:{owner['id']}"]
    after = instruments(household_positions(e.store, tick=5))[f"property:{project}:agent:{heir['id']}"]
    assert before["holder"] == {"type": "agent", "id": owner["id"]}
    assert after["quantity"] == {"numerator": "1", "denominator": "1"}
    assert after["mark"] is None and after["face_cents"] is None
    assert after["original_holder"] == before["original_holder"]


def test_empty_issuance_is_recorded_and_missing_history_cannot_be_guessed(estate_case):
    e, _, person, *_ = estate_case
    empty = e.firms.found_firm(0, person, "No issued units", "manufacturing", shares=0)
    assert e.store.scalar("SELECT qty FROM share_movements WHERE firm_id=? AND movement_type='founder_issuance'", (empty,)) == 0
    committed(e, 0)
    assert not any(row["kind"] == "equity" for row in household_positions(e.store, tick=0)["instruments"])
    # An old unpublished Sem20 artifact has no defensible original cap table.
    e.store.execute("DELETE FROM share_movements WHERE firm_id=?", (empty,))
    before = canonical_hashes(e.store)
    with pytest.raises(ValueError, match="lacks recorded founder issuance"):
        household_positions(e.store, tick=0)
    assert canonical_hashes(e.store) == before


def test_household_property_aggregation_preserves_two_children_fractions_after_a_later_death(property_world):
    world, owner, guardian = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    children = [e.households.birth(tick, owner["id"]) for tick in (3, 4)]
    join_household(e, guardian["id"], owner["id"], 4)
    e.lifecycle.settle_death(5, owner["id"])
    committed(e, 5)
    old = household_positions(e.store, tick=5)
    shares = [r for r in old["instruments"] if r["key"].startswith(f"property:{project}:")]
    assert len(shares) == 2
    assert all(r["quantity"] == {"numerator": "1", "denominator": "2"} for r in shares)
    same_home = home(old, children[0])
    assert children[1] in same_home["members"]
    assert all(same_home["asset_keys"].count(r["key"]) == 1 for r in shares)
    e.store.insert("social_ties", agent_a=children[0], agent_b=children[1], weight=10)
    e.lifecycle.settle_death(6, children[0])
    committed(e, 6)
    assert household_positions(e.store, tick=5) == old
    current = instruments(household_positions(e.store, tick=6))
    assert current[f"property:{project}:agent:{children[1]}"]["quantity"] == {"numerator": "1", "denominator": "1"}


def test_reader_detects_unjournaled_share_changes_without_writing_a_repair(estate_case):
    e, _, person, *_ = estate_case
    firm = e.firms.found_firm(0, person, "Recorded issuer", "manufacturing", shares=100)
    committed(e, 0)
    assert instruments(household_positions(e.store, tick=0))[f"shares:{firm}:agent:{person}"]["quantity"] == "100"
    e.store.execute("UPDATE shares SET qty=99 WHERE firm_id=?", (firm,))
    before = canonical_hashes(e.store)
    with pytest.raises(ValueError, match="committed cap table"):
        household_positions(e.store, tick=0)
    assert canonical_hashes(e.store) == before


@pytest.mark.parametrize("funding", ["legacy_vc", "typed_round"])
def test_funded_pitch_and_round_are_one_issuance_and_do_not_create_a_market_mark(estate_case, funding):
    e, bank, founder, *_ = estate_case
    investor, wallet = make_agent(e, bank, "Investor", cash=500, region_id=1,
                                 kind="staff", role="vc_partner", occupation="venture capitalist")
    lawyer, _ = make_agent(e, bank, "Counsel", cash=0, region_id=1,
                           kind="staff", role="lawyer", occupation="lawyer")
    for person in (investor, lawyer):
        e.households.register_person(0, person, "genesis")
    firm = e.firms.found_firm(0, founder, "Private capital", "manufacturing", shares=100)
    pitch = e.vc.pitch(1, firm, founder, 100, "Declared funding scenario")
    if funding == "legacy_vc":
        result = e.vc.fund(2, pitch, investor, 100, 2000)
    else:
        from engine.actions import ActionExecutor
        actions = ActionExecutor(e)
        result = actions.execute_action(2, investor, {"type": "propose_term_sheet", "firm_id": firm,
            "instrument_type": "preferred_equity", "amount_cents": 100, "pre_money_cents": 400,
            "equity_bps": 2000, "metadata": {"pitch_id": pitch}})
        assert result["ok"], result
        sheet = result["term_sheet_id"]
        assert actions.execute_action(2, founder, {"type": "accept_term_sheet", "term_sheet_id": sheet})["ok"]
        assert actions.execute_action(2, lawyer, {"type": "run_due_diligence", "term_sheet_id": sheet})["ok"]
        result = actions.execute_action(2, investor, {"type": "close_funding_round", "term_sheet_id": sheet})
    assert result["ok"], result
    assert e.store.scalar("SELECT status FROM pitches WHERE id=?", (pitch,)) == "funded"
    committed(e, 2)
    prior = instruments(household_positions(e.store, tick=1))
    assert f"shares:{firm}:agent:{investor}" not in prior
    report = household_positions(e.store, tick=2)
    rows = instruments(report)
    assert rows[f"shares:{firm}:agent:{investor}"]["quantity"] == "25"
    assert rows[f"shares:{firm}:agent:{founder}"]["quantity"] == "100"
    assert rows[f"shares:{firm}:agent:{investor}"]["mark"] is None
    assert home(report, investor)["by_currency"]["USD"]["wallet_cash_cents"] == 400
    assert e.ledger.balance(wallet) == 400 and e.ledger.reconcile()[0]
