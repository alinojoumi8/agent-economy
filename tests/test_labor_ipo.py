import json
import random

from agents.memory import Memory
from agents.participant import ParticipantService
from agents.prompts import ContextBuilder
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.store import Store
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank


def _modern_economy(store):
    config = {
        "engine_semantics_version": 6,
        "central_bank": {"max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2000},
        "participant_mode": {"enabled": True},
    }
    economy = Economy(store, config, random.Random(11), random.Random(12))
    economy.ensure_system_accounts()
    return economy, config, ActionExecutor(economy)


def _semantics7_economy(store, *, supply_recovery=None):
    config = {
        "engine_semantics_version": 7,
        "central_bank": {"max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2000},
        "participant_mode": {"enabled": True},
    }
    if supply_recovery is not None:
        config["supply_recovery"] = supply_recovery
    economy = Economy(store, config, random.Random(15), random.Random(16))
    economy.ensure_system_accounts()
    return economy, config, ActionExecutor(economy)


def _legacy_economy(store):
    config = {
        "engine_semantics_version": 5,
        "central_bank": {"max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2000},
    }
    economy = Economy(store, config, random.Random(13), random.Random(14))
    economy.ensure_system_accounts()
    return economy, config


def _firm(economy, founder_id, *, capital=200_000):
    return economy.firms.found_firm(
        0, founder_id, "Negotiated Industries", "services",
        opening_capital_cents=capital, shares=1_000)


def test_wage_offer_counter_and_accept_is_bilateral_persisted_and_audited(store):
    economy, config, executor = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Worker", cash=50_000)
    stranger, _ = make_agent(economy, bank_id, name="Stranger", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)

    # Modern runs cannot bypass the candidate with the legacy direct-hire path.
    direct = executor.execute_action(
        2, founder, {"type": "hire", "application_id": application_id})
    assert not direct["ok"]
    assert "wage offer" in direct["reason"]

    first = executor.execute_action(2, founder, {
        "type": "make_job_offer", "application_id": application_id, "wage": 190_00,
    })
    assert first["ok"]
    assert not executor.execute_action(2, stranger, {
        "type": "accept_job_offer", "offer_id": first["offer_id"],
    })["ok"]
    assert not executor.execute_action(2, founder, {
        "type": "counter_job_offer", "offer_id": first["offer_id"], "wage": 195_00,
    })["ok"]

    counter = executor.execute_action(3, worker, {
        "type": "counter_job_offer", "offer_id": first["offer_id"], "wage": 205_00,
    })
    assert counter["ok"]
    assert store.query_one("SELECT status FROM job_offers WHERE id=?", (first["offer_id"],))[
        "status"] == "superseded"
    # A superseded physical offer ID cannot be replayed as a live capability.
    assert not executor.execute_action(3, worker, {
        "type": "accept_job_offer", "offer_id": first["offer_id"],
    })["ok"]

    accepted = executor.execute_action(4, founder, {
        "type": "accept_job_offer", "offer_id": counter["offer_id"],
    })
    assert accepted["ok"]
    employment = store.query_one("SELECT * FROM employments WHERE id=?", (accepted["employment_id"],))
    assert int(employment["agent_id"]) == worker
    assert int(employment["firm_id"]) == firm_id
    assert int(employment["wage_cents"]) == 205_00
    assert store.query_one("SELECT state FROM applications WHERE id=?", (application_id,))[
        "state"] == "hired"
    assert store.query_one("SELECT status FROM job_offers WHERE id=?", (counter["offer_id"],))[
        "status"] == "accepted"

    hired = store.query_one("SELECT payload_json FROM events WHERE kind='hired' ORDER BY id DESC LIMIT 1")
    payload = json.loads(hired["payload_json"])
    assert payload["job_offer_id"] == counter["offer_id"]
    assert payload["negotiated"] is True
    assert int(store.scalar(
        "SELECT COUNT(*) FROM action_proposals WHERE action_type IN "
        "('make_job_offer','counter_job_offer','accept_job_offer')")) >= 6

    # The same persisted capability IDs are exposed to LLM and participant paths.
    context_builder = ContextBuilder(economy, Memory(store, config), config)
    service = ParticipantService(store, context_builder, config)
    # Re-open a second application to inspect both sides' bounded surfaces.
    second_job = economy.labor.post_job(5, firm_id, "Analyst", 220_00)
    second_application = economy.labor.apply_job(5, stranger, second_job)
    second_offer = executor.execute_action(5, founder, {
        "type": "make_job_offer", "application_id": second_application, "wage": 210_00,
    })
    candidate = store.query_one("SELECT * FROM agents WHERE id=?", (stranger,))
    candidate_context = context_builder.build(candidate, 6)
    assert candidate_context["incoming_job_offers"][0]["offer_id"] == second_offer["offer_id"]
    system, prompt = context_builder.render_prompt(candidate_context)
    assert "counter_job_offer" in system
    assert "hire{application_id}" not in system
    assert str(second_offer["offer_id"]) in prompt
    assert "Resolve one supplied wage offer" in prompt
    assert "do not apply again" in prompt
    candidate_catalog = service.action_catalog(stranger)
    assert any(item["type"] == "accept_job_offer" and item["enabled"]
               for item in candidate_catalog)
    second_counter = executor.execute_action(6, stranger, {
        "type": "counter_job_offer", "offer_id": second_offer["offer_id"], "wage": 220_00,
    })
    founder_catalog = service.action_catalog(founder)
    assert any(item["type"] == "accept_job_offer" and item["variant"] == "firm"
               and item["enabled"] for item in founder_catalog)
    assert context_builder.build(store.query_one(
        "SELECT * FROM agents WHERE id=?", (founder,)), 7)["firm_job_offers"][0][
            "offer_id"] == second_counter["offer_id"]


def test_accept_job_offer_rejects_non_integer_identifiers(store):
    economy, _, executor = _modern_economy(store)
    bank_id = make_bank(economy)
    actor, _ = make_agent(economy, bank_id, name="Actor", cash=50_000)

    for offer_id in (None, "1", 1.5, True, 0):
        result = executor.execute_action(
            1,
            actor,
            {"type": "accept_job_offer", "offer_id": offer_id},
        )
        assert result == {
            "ok": False,
            "reason": "offer_id must be a positive integer",
        }


def test_incompatible_offer_cleanup_includes_missing_candidate_wallets(store):
    economy, _, _ = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Founder", cash=1_000_000)
    missing_wallet, _ = make_agent(
        economy, bank_id, name="Missing Wallet", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, missing_wallet, job_id)
    offer_id = economy.labor.make_offer(
        1, application_id, founder, 200_00)
    store.update("agents", missing_wallet, checking_account_id=None)

    expired = economy.labor.expire_incompatible_offers(2, phase="MARKET")

    assert expired == 1
    assert store.scalar(
        "SELECT status FROM job_offers WHERE id=?", (offer_id,)) == "expired"
    assert store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='job_offer_expired_incompatible_currency' "
        "AND phase='MARKET'") == 1


def test_negotiated_hire_rejects_cross_currency_at_every_transition(store):
    economy, _, executor = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Currency Founder", cash=1_000_000)
    worker, worker_account = make_agent(
        economy, bank_id, name="Currency Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Treasurer", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)

    # The modern invariant is unconditional: it applies even though this test's
    # config leaves llm.local_currency_action_surfaces disabled.
    store.execute(
        "UPDATE accounts SET currency_code='EUR' WHERE id=?", (worker_account,))
    rejected_offer = executor.execute_action(2, founder, {
        "type": "make_job_offer", "application_id": application_id, "wage": 190_00,
    })
    assert not rejected_offer["ok"]
    assert store.scalar("SELECT COUNT(*) FROM job_offers") == 0

    store.execute(
        "UPDATE accounts SET currency_code='USD' WHERE id=?", (worker_account,))
    first = executor.execute_action(3, founder, {
        "type": "make_job_offer", "application_id": application_id, "wage": 190_00,
    })
    assert first["ok"]
    store.execute(
        "UPDATE accounts SET currency_code='EUR' WHERE id=?", (worker_account,))
    rejected_counter = executor.execute_action(4, worker, {
        "type": "counter_job_offer", "offer_id": first["offer_id"], "wage": 205_00,
    })
    assert not rejected_counter["ok"]
    assert store.scalar(
        "SELECT status FROM job_offers WHERE id=?", (first["offer_id"],)) == "pending"

    store.execute(
        "UPDATE accounts SET currency_code='USD' WHERE id=?", (worker_account,))
    counter = executor.execute_action(5, worker, {
        "type": "counter_job_offer", "offer_id": first["offer_id"], "wage": 205_00,
    })
    assert counter["ok"]
    store.execute(
        "UPDATE accounts SET currency_code='EUR' WHERE id=?", (worker_account,))
    rejected_acceptance = executor.execute_action(6, founder, {
        "type": "accept_job_offer", "offer_id": counter["offer_id"],
    })
    assert not rejected_acceptance["ok"]
    assert store.scalar("SELECT COUNT(*) FROM employments") == 0

    # NIGHT_CLOSE payroll remains safe because no cross-currency employment was
    # created for the posting engine to process.
    opening_worker_cash = economy.ledger.balance(worker_account)
    economy.firms.process_payroll(30)
    assert economy.ledger.balance(worker_account) == opening_worker_cash
    assert store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='payroll'") == 0


def test_expiring_stale_job_terminalizes_every_actionable_application_when_opted_in(store):
    """Recovery may clean up applications that legacy expiry deliberately retains."""
    economy, _, _ = _semantics7_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Expiry Founder", cash=1_000_000)
    pending_worker, _ = make_agent(economy, bank_id, name="Pending Worker", cash=50_000)
    negotiating_worker, _ = make_agent(
        economy, bank_id, name="Negotiating Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    pending_application = economy.labor.apply_job(1, pending_worker, job_id)
    negotiating_application = economy.labor.apply_job(1, negotiating_worker, job_id)
    offer_id = economy.labor.make_offer(
        1, negotiating_application, founder, 200_00)

    assert pending_application is not None
    assert negotiating_application is not None
    assert offer_id is not None
    store.update("jobs", job_id, status="closed")

    economy.labor.expire_stale_jobs(22, terminalize_stale_applications=True)

    assert store.scalar("SELECT status FROM jobs WHERE id=?", (job_id,)) == "closed"
    assert store.scalar(
        "SELECT state FROM applications WHERE id=?", (pending_application,)) == "rejected"
    assert store.scalar(
        "SELECT state FROM applications WHERE id=?", (negotiating_application,)) == "rejected"
    assert store.scalar("SELECT status FROM job_offers WHERE id=?", (offer_id,)) == "expired"


def test_active_recovery_hides_closed_job_application_from_semantics7_context(store):
    """Active recovery suppresses a closed vacancy from its founder's action surface."""
    economy, config, _ = _semantics7_economy(
        store, supply_recovery={"enabled": True, "activation_tick": 0})
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Context Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Context Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)
    assert application_id is not None
    store.update("jobs", job_id, status="closed")

    founder_row = store.query_one("SELECT * FROM agents WHERE id=?", (founder,))
    builder = ContextBuilder(economy, Memory(store, config), config)
    context = builder.build(founder_row, 2)

    assert context["firm_applications"] == []


def test_feature_off_semantics7_context_keeps_closed_job_application(store):
    """Feature-off Semantics 7 retains the historical closed-vacancy context."""
    economy, config, _ = _semantics7_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Feature-off Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Feature-off Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)
    assert application_id is not None
    store.update("jobs", job_id, status="closed")

    founder_row = store.query_one("SELECT * FROM agents WHERE id=?", (founder,))
    builder = ContextBuilder(economy, Memory(store, config), config)
    context = builder.build(founder_row, 2)

    assert [row["application_id"] for row in context["firm_applications"]] == [application_id]
    assert [row["application_id"] for row in builder._firm_applications(firm_id)] == [
        application_id]


def test_feature_off_legacy_context_keeps_closed_job_application(store):
    """The pre-negotiation context keeps its legacy closed-vacancy rows too."""
    economy, config = _legacy_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Legacy Context Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Legacy Context Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)
    assert application_id is not None
    store.update("jobs", job_id, status="closed")

    founder_row = store.query_one("SELECT * FROM agents WHERE id=?", (founder,))
    builder = ContextBuilder(economy, Memory(store, config), config)
    context = builder.build(founder_row, 2)

    assert [row["application_id"] for row in context["firm_applications"]] == [application_id]
    assert [row["application_id"] for row in builder._firm_applications(
        firm_id, include_posted_wage=True)] == [application_id]


def test_recovery_context_hides_closed_job_counteroffer_only_after_activation(store):
    """Context filtering starts at recovery activation, not merely profile presence."""
    economy, config, _ = _semantics7_economy(
        store, supply_recovery={"enabled": True, "activation_tick": 5})
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Counter Context Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Counter Context Worker", cash=50_000)
    firm_id = _firm(economy, founder)
    job_id = economy.labor.post_job(1, firm_id, "Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)
    assert application_id is not None
    opening_offer = economy.labor.make_offer(1, application_id, founder, 200_00)
    counteroffer = economy.labor.make_offer(
        2, application_id, worker, 210_00, parent_offer_id=opening_offer)
    assert counteroffer is not None
    store.update("jobs", job_id, status="closed")

    founder_row = store.query_one("SELECT * FROM agents WHERE id=?", (founder,))
    builder = ContextBuilder(economy, Memory(store, config), config)
    before_activation = builder.build(founder_row, 4)
    after_activation = builder.build(founder_row, 5)

    assert [row["application_id"] for row in before_activation["firm_applications"]] == [
        application_id]
    assert [row["offer_id"] for row in before_activation["firm_job_offers"]] == [
        counteroffer]
    assert after_activation["firm_applications"] == []
    assert after_activation["firm_job_offers"] == []


def test_ipo_requires_qualification_and_agent_bids_drive_price_cash_and_cap_table(store):
    economy, config, executor = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Issuer", cash=1_000_000)
    bidder_a, bidder_a_account = make_agent(economy, bank_id, name="Bidder A", cash=100_000)
    bidder_b, bidder_b_account = make_agent(economy, bank_id, name="Bidder B", cash=100_000)
    outsider, _ = make_agent(economy, bank_id, name="Outsider", cash=100_000)
    firm_id = _firm(economy, founder)
    manager, _ = make_agent(
        economy, bank_id, name="Issuer Manager", cash=100_000, role="manager")
    store.update("agents", manager, employer_id=firm_id)
    firm_account = int(store.scalar("SELECT account_id FROM firms WHERE id=?", (firm_id,)))
    opening_firm_cash = economy.ledger.balance(firm_account)

    too_young = executor.execute_action(29, founder, {
        "type": "open_ipo", "firm_id": firm_id, "shares_offered": 100,
        "reserve_price": 100,
    })
    assert not too_young["ok"]
    assert not executor.execute_action(30, outsider, {
        "type": "open_ipo", "firm_id": firm_id, "shares_offered": 100,
        "reserve_price": 100,
    })["ok"]

    opened = executor.execute_action(30, founder, {
        "type": "open_ipo", "firm_id": firm_id, "shares_offered": 100,
        "reserve_price": 100, "minimum_subscription_bps": 5000,
    })
    assert opened["ok"]
    offering_id = opened["offering_id"]
    assert economy.exchange.last_price(firm_id) is None
    context_builder = ContextBuilder(economy, Memory(store, config), config)
    bidder_catalog = ParticipantService(store, context_builder, config).action_catalog(bidder_a)
    assert any(item["type"] == "place_ipo_bid" and item["enabled"]
               for item in bidder_catalog)
    controller_bid = executor.execute_action(31, manager, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 10, "max_price": 150,
    })
    assert not controller_bid["ok"]
    assert "controller" in controller_bid["reason"]
    assert not executor.execute_action(31, bidder_a, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 1_000, "max_price": 1_000,
    })["ok"]

    bid_a = executor.execute_action(31, bidder_a, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 70, "max_price": 150,
    })
    # Each bid is individually affordable, but all open commitments in the
    # issuer currency must remain covered in aggregate.
    overcommitted = executor.execute_action(31, bidder_a, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 600, "max_price": 150,
    })
    bid_b = executor.execute_action(31, bidder_b, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 60, "max_price": 120,
    })
    assert bid_a["ok"] and bid_b["ok"]
    assert not overcommitted["ok"]
    assert "commitment" in overcommitted["reason"]
    assert not executor.execute_action(32, outsider, {
        "type": "close_ipo", "offering_id": offering_id,
    })["ok"]

    closed = executor.execute_action(32, founder, {
        "type": "close_ipo", "offering_id": offering_id,
    })
    assert closed == {
        "ok": True, "firm_id": firm_id, "offering_id": offering_id,
        "clearing_price_cents": 120, "shares_sold": 100,
        "proceeds_cents": 12_000,
    }
    firm = store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
    assert firm["status"] == "listed"
    assert int(firm["shares_outstanding"]) == 1_100
    assert economy.exchange.shares_held(firm_id, "agent", bidder_a) == 70
    assert economy.exchange.shares_held(firm_id, "agent", bidder_b) == 30
    assert economy.ledger.balance(firm_account) == opening_firm_cash + 12_000
    assert economy.ledger.balance(bidder_a_account) == 100_000 - 8_400
    assert economy.ledger.balance(bidder_b_account) == 100_000 - 3_600
    assert economy.exchange.last_price(firm_id) == 120

    movements = store.query(
        "SELECT sm.*,t.kind FROM share_movements sm JOIN transactions t "
        "ON t.id=sm.transaction_id WHERE sm.reference_type='ipo_bid' ORDER BY sm.id")
    assert [(int(row["qty"]), int(row["price_cents"]), row["kind"])
            for row in movements] == [(70, 120, "ipo_subscription"),
                                      (30, 120, "ipo_subscription")]
    assert sum(int(row["amount_cents"]) for row in movements) == 12_000
    ok, diagnostics = economy.ledger.reconcile()
    assert ok, diagnostics


def test_ipo_price_discovery_excludes_bids_unfunded_at_close(store):
    economy, _, executor = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Funding Issuer", cash=1_000_000)
    manipulator, manipulator_account = make_agent(
        economy, bank_id, name="Unfunded Bidder", cash=20_000)
    funded_bidder, _ = make_agent(
        economy, bank_id, name="Funded Bidder", cash=20_000)
    sink, sink_account = make_agent(economy, bank_id, name="Cash Sink", cash=0)
    firm_id = _firm(economy, founder)
    opened = executor.execute_action(30, founder, {
        "type": "open_ipo", "firm_id": firm_id, "shares_offered": 100,
        "reserve_price": 100, "minimum_subscription_bps": 5000,
    })
    assert opened["ok"]
    offering_id = opened["offering_id"]
    high = executor.execute_action(31, manipulator, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 100, "max_price": 200,
    })
    market = executor.execute_action(31, funded_bidder, {
        "type": "place_ipo_bid", "offering_id": offering_id,
        "qty": 100, "max_price": 100,
    })
    assert high["ok"] and market["ok"]

    # A later legitimate spend removes the high bid's funding.  That bid must
    # no longer establish either demand or the marginal price.
    economy.ledger.transfer(
        31, manipulator_account, sink_account, 20_000,
        kind="consumer_transfer", memo="spend after IPO bid")
    closed = executor.execute_action(32, founder, {
        "type": "close_ipo", "offering_id": offering_id,
    })
    assert closed["ok"]
    assert closed["clearing_price_cents"] == 100
    assert closed["shares_sold"] == 100
    assert store.scalar(
        "SELECT status FROM ipo_bids WHERE id=?", (high["bid_id"],)) == "rejected"
    assert store.scalar(
        "SELECT qty_allocated FROM ipo_bids WHERE id=?", (market["bid_id"],)) == 100
    assert economy.ledger.balance(manipulator_account) == 0
    assert economy.ledger.balance(sink_account) == 20_000


def test_bootstrap_listing_has_shareholders_but_no_engine_invented_price(store):
    economy, _, _ = _modern_economy(store)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Bootstrap Founder", cash=500_000)
    firm_id = _firm(economy, founder, capital=100_000)

    economy.firms.list_firm(0, firm_id, None, 0)

    assert store.scalar("SELECT status FROM firms WHERE id=?", (firm_id,)) == "listed"
    assert economy.exchange.last_price(firm_id) is None
    event = store.query_one(
        "SELECT payload_json FROM events WHERE kind='bootstrap_listing' AND subject_id=?",
        (firm_id,))
    assert json.loads(event["payload_json"])["reference_price_cents"] is None


def _populate_labor_ipo_replay_fixture(path, run_id):
    store = Store(str(path))
    config = {
        "engine_semantics_version": 6,
        "central_bank": {
            "max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2000,
        },
        "participant_mode": {"enabled": True},
    }
    store.init_run_meta(run_id, 99, config)
    economy = Economy(store, config, random.Random(11), random.Random(12))
    economy.ensure_system_accounts()
    executor = ActionExecutor(economy)
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Replay Founder", cash=1_000_000)
    worker, _ = make_agent(economy, bank_id, name="Replay Worker", cash=50_000)
    bidder, _ = make_agent(economy, bank_id, name="Replay Bidder", cash=100_000)
    firm_id = _firm(economy, founder)

    job_id = economy.labor.post_job(1, firm_id, "Replay Operator", 200_00)
    application_id = economy.labor.apply_job(1, worker, job_id)
    offer = executor.execute_action(2, founder, {
        "type": "make_job_offer", "application_id": application_id, "wage": 190_00,
    })
    counter = executor.execute_action(3, worker, {
        "type": "counter_job_offer", "offer_id": offer["offer_id"], "wage": 205_00,
    })
    assert executor.execute_action(4, founder, {
        "type": "accept_job_offer", "offer_id": counter["offer_id"],
    })["ok"]

    opened = executor.execute_action(30, founder, {
        "type": "open_ipo", "firm_id": firm_id, "shares_offered": 100,
        "reserve_price": 100, "minimum_subscription_bps": 5000,
    })
    bid = executor.execute_action(31, bidder, {
        "type": "place_ipo_bid", "offering_id": opened["offering_id"],
        "qty": 100, "max_price": 120,
    })
    assert bid["ok"]
    assert executor.execute_action(32, founder, {
        "type": "close_ipo", "offering_id": opened["offering_id"],
    })["ok"]
    store.set_meta(tick=32)
    store.close()


def test_populated_wage_and_ipo_tables_replay_exactly(tmp_path):
    source = tmp_path / "labor-ipo-source.db"
    replay = tmp_path / "labor-ipo-replay.db"
    _populate_labor_ipo_replay_fixture(source, "labor-ipo-source")
    _populate_labor_ipo_replay_fixture(replay, "labor-ipo-replay")

    proof = verify_replay(source, replay)
    assert proof["exact"] is True, proof["differences"]
    assert proof["differences"] == []
    table_rows = {
        item["table"]: item["source_rows"] for item in proof["tables"]
    }
    for table in ("job_offers", "ipo_offerings", "ipo_bids", "share_movements"):
        assert table_rows[table] > 0
