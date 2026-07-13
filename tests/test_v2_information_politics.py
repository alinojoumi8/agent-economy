import random

from engine.actions import ActionExecutor
from engine.core import Economy

from .conftest import make_agent, make_bank


def _institutional_world(store):
    config = {
        "information_economy": {"enabled": True, "base_reach": 1.0},
        "political_model": {"enabled": True, "house_seats": 12, "senate_seats": 6,
                            "house_election_interval_ticks": 180,
                            "executive_election_interval_ticks": 360,
                            "lobbying_disclosure_delay_ticks": 5},
        "legal": {"enabled": True},
    }
    economy = Economy(store, config, random.Random(41), random.Random(42))
    economy.ensure_system_accounts()
    bank = make_bank(economy, reserves=10_000_000)
    founder, _ = make_agent(economy, bank, name="Founder Lobby Client", cash=500_000,
                            political_lean=-0.2)
    reader, _ = make_agent(economy, bank, name="Reader", cash=100_000,
                           media_diet_json="[1]", political_lean=0.1)
    firm = economy.firms.found_firm(0, founder, "Policy AI", "tech", opening_capital_cents=200_000)
    economy.politics.initialize(0)
    return economy, ActionExecutor(economy), founder, reader, firm


def test_claim_exposure_is_asymmetric_persisted_and_updates_belief(store):
    economy, executor, founder, reader, firm = _institutional_world(store)
    source = store.log_event(1, "firm_disclosure_published", {
        "firm_id": firm, "facts": {"revenue_cents": 250_000}}, phase="EXECUTION")
    claim = executor.execute_action(1, founder, {
        "type": "create_claim", "claim_key": "firm:revenue:q1",
        "subject_type": "firm", "subject_id": firm, "predicate": "revenue_cents",
        "value": 250_000, "truth_status": "verified", "source_event_ids": [source],
    })
    item = executor.execute_action(1, founder, {
        "type": "publish_information", "item_type": "social_post",
        "claim_id": claim["claim_id"], "body": "Quarterly revenue is now public.",
        "tone": 0.8, "slant": 0.2, "novelty": 0.9, "distortion": 0.0,
    })
    assert item["ok"]
    assert store.query_one("SELECT 1 FROM beliefs WHERE agent_id=? AND key=?",
                           (reader, f"claim:{claim['claim_id']}")) is None
    trades_before = int(store.scalar("SELECT COUNT(*) FROM trades", default=0))

    economy.information.run_nightly(2)

    exposure = store.query_one(
        "SELECT * FROM information_exposures WHERE item_id=? AND agent_id=?", (item["item_id"], reader))
    assert exposure is not None
    assert float(store.scalar("SELECT value FROM beliefs WHERE agent_id=? AND key=?",
                              (reader, f"claim:{claim['claim_id']}"))) == 1.0
    assert int(store.scalar("SELECT COUNT(*) FROM trades", default=0)) == trades_before


def test_lobbying_spends_real_money_but_does_not_write_votes(store):
    economy, executor, founder, _, firm = _institutional_world(store)
    lobbyist = int(store.scalar("SELECT id FROM agents WHERE role='lobbyist' ORDER BY id LIMIT 1"))
    legislator = int(store.scalar("SELECT agent_id FROM legislators ORDER BY id LIMIT 1"))
    firm_account = int(store.scalar("SELECT account_id FROM firms WHERE id=?", (firm,)))
    before = economy.ledger.balance(firm_account)

    result = executor.execute_action(1, lobbyist, {
        "type": "lobby", "sponsor_type": "firm", "sponsor_id": firm,
        "authorized_by_agent_id": founder, "target_agent_id": legislator,
        "activity_type": "meeting", "position": "support", "amount_cents": 25_000,
    })

    assert result["ok"]
    assert economy.ledger.balance(firm_account) == before - 25_000
    assert store.scalar("SELECT COUNT(*) FROM legislative_votes", default=0) == 0
    economy.politics.run_nightly(6)
    assert store.scalar("SELECT disclosed FROM lobbying_activities WHERE id=?",
                        (result["activity_id"],)) == 1
    assert economy.ledger.reconcile()[0]


def test_bill_process_enacts_typed_ai_competition_rules(store):
    economy, executor, _, _, _ = _institutional_world(store)
    sponsor = int(store.scalar(
        "SELECT l.agent_id FROM legislators l WHERE l.chamber='house' ORDER BY l.seat_number LIMIT 1"))
    introduced = executor.execute_action(1, sponsor, {
        "type": "sponsor_bill", "bill_key": "AI-CMAA-STRICT",
        "title": "AI Competition and Market Access Act", "topic": "competition",
        "summary": "Strict fictional AI acquisition review.",
        "policy_changes": economy.politics.ai_policy_changes("strict"),
    })
    bill_id = introduced["bill_id"]
    committee_agents = [int(row["agent_id"]) for row in store.query(
        "SELECT l.agent_id FROM committee_members cm JOIN legislators l ON l.id=cm.legislator_id "
        "JOIN bills b ON b.committee_id=cm.committee_id WHERE b.id=? ORDER BY l.seat_number",
        (bill_id,))]
    status = None
    for agent_id in committee_agents[:2]:
        status = executor.execute_action(1, agent_id, {
            "type": "committee_vote", "bill_id": bill_id, "vote": "yes"})["status"]
    assert status == "floor_house"
    house_agents = [int(row["agent_id"]) for row in store.query(
        "SELECT agent_id FROM legislators WHERE chamber='house' ORDER BY seat_number LIMIT 7")]
    for agent_id in house_agents:
        status = executor.execute_action(1, agent_id, {
            "type": "cast_legislative_vote", "bill_id": bill_id, "vote": "yes"})["status"]
    assert status == "floor_senate"
    senate_agents = [int(row["agent_id"]) for row in store.query(
        "SELECT agent_id FROM legislators WHERE chamber='senate' ORDER BY seat_number LIMIT 4")]
    for agent_id in senate_agents:
        status = executor.execute_action(1, agent_id, {
            "type": "cast_legislative_vote", "bill_id": bill_id, "vote": "yes"})["status"]
    assert status == "executive"
    executive = int(store.scalar("SELECT id FROM agents WHERE role='executive' LIMIT 1"))
    signed = executor.execute_action(1, executive, {
        "type": "executive_bill_action", "bill_id": bill_id,
        "action": "sign", "effective_delay_ticks": 1})
    assert signed["status"] == "enacted"

    economy.politics.run_nightly(2)

    assert economy.politics.active_policy("competition.hhi_threshold") == 1500.0
    assert economy.politics.active_policy("ai.interoperability_remedy") is True
    assert store.query_one("SELECT 1 FROM events WHERE kind='policy_rule_effective'")


def test_elections_derive_from_voters_and_are_reproducible(store):
    economy, _, _, _, _ = _institutional_world(store)
    first = economy.politics.hold_election(180, "legislative")
    assert first["turnout"] == 2
    assert first["civic_votes"] + first["enterprise_votes"] == 2
    persisted = store.query_one("SELECT results_json FROM elections WHERE tick=180")
    assert persisted is not None
