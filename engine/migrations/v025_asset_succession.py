"""Estate rights and effective stewardship for Semantics 20 (in development)."""

NAME = "estate_assets_and_business_succession"
ESTATE_TABLES = ("estate_cases", "estate_beneficiaries", "estate_items", "estate_claims",
                 "estate_claim_losses", "estate_receipts", "estate_cash_offsets", "estate_disbursements")
PROJECT_TABLES = ("project_interest_lots", "project_stewardships")
AWARD_TABLES = ("legal_awards", "legal_award_obligations", "legal_award_payments", "estate_claim_releases",
                "legal_wage_scopes", "legal_wage_awards", "wage_claim_novations", "legal_award_losses")
DISPUTE_TABLES = ("estate_legal_reserves", "estate_reserve_obligations", "estate_reserve_resolutions")
SECURITY_TABLES = ("estate_security_lots", "estate_security_releases", "estate_security_orders",
                   "estate_security_sales", "estate_security_sale_lots",
                   "estate_unlisted_bids", "estate_unlisted_bid_ends", "estate_unlisted_sales")
PROPERTY_CUSTODY_TABLES = ("estate_project_custody", "estate_project_releases",
                          "estate_property_bids", "estate_property_bid_ends", "estate_property_sales")
ADMINISTRATION_TABLES = ("estate_administrations", "estate_administration_ends")
AUTHORITY_TABLES = ("legal_decision_authorities",)
REPRESENTATION_TABLES = ("legal_action_authorities", "legal_counsel_requests", "legal_counsel_responses", "legal_counsel_ends")
SQL = """
CREATE TABLE legal_action_authorities (
    id INTEGER PRIMARY KEY,
    matter_id INTEGER NOT NULL REFERENCES legal_matters(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    action TEXT NOT NULL CHECK(action IN ('file_claim','submit_filing','propose_settlement','accept_settlement','request_legal_counsel','end_legal_counsel')),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    side TEXT NOT NULL CHECK(side IN ('claimant','respondent')),
    party_type TEXT NOT NULL,
    party_id INTEGER NOT NULL,
    capacity TEXT NOT NULL CHECK(capacity IN ('self','organization','estate','counsel')),
    estate_id INTEGER REFERENCES estate_cases(id),
    counsel_request_id INTEGER REFERENCES legal_counsel_requests(id),
    proof_json TEXT NOT NULL,
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    effect_event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK(effect_event_id>event_id)
);
CREATE INDEX ix_legal_action_authority_matter ON legal_action_authorities(matter_id,id);
CREATE UNIQUE INDEX ix_legal_claim_authority ON legal_action_authorities(matter_id) WHERE action='file_claim';
CREATE UNIQUE INDEX ix_legal_settlement_authority ON legal_action_authorities(matter_id) WHERE action='accept_settlement';
CREATE TABLE legal_counsel_requests (
    id INTEGER PRIMARY KEY,
    matter_id INTEGER NOT NULL REFERENCES legal_matters(id),
    side TEXT NOT NULL CHECK(side IN ('claimant','respondent')),
    requester_id INTEGER NOT NULL REFERENCES agents(id),
    counsel_id INTEGER NOT NULL REFERENCES agents(id),
    requested_tick INTEGER NOT NULL CHECK(requested_tick>=0),
    expires_tick INTEGER NOT NULL CHECK(expires_tick>requested_tick),
    scopes_json TEXT NOT NULL,
    authority_event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK(requester_id<>counsel_id AND event_id>authority_event_id)
);
CREATE INDEX ix_legal_counsel_matter ON legal_counsel_requests(matter_id,side,id);
CREATE TABLE legal_counsel_responses (
    id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL UNIQUE REFERENCES legal_counsel_requests(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    actor_age INTEGER NOT NULL CHECK(actor_age>=18),
    decision TEXT NOT NULL CHECK(decision IN ('accepted','declined')),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TABLE legal_counsel_ends (
    id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL UNIQUE REFERENCES legal_counsel_requests(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    actor_id INTEGER REFERENCES agents(id),
    reason TEXT NOT NULL CHECK(reason IN ('withdrawn','revoked','expired','client_authority_lost','counsel_unavailable','matter_closed')),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TRIGGER legal_counsel_one_current BEFORE INSERT ON legal_counsel_requests
WHEN EXISTS(SELECT 1 FROM legal_counsel_requests r WHERE r.matter_id=NEW.matter_id AND r.side=NEW.side
    AND NOT EXISTS(SELECT 1 FROM legal_counsel_ends e WHERE e.request_id=r.id)
    AND NOT EXISTS(SELECT 1 FROM legal_counsel_responses a WHERE a.request_id=r.id AND a.decision='declined'))
BEGIN SELECT RAISE(ABORT,'matter side already has a current counsel request'); END;
CREATE TABLE legal_decision_authorities (
    id INTEGER PRIMARY KEY,
    decision_id INTEGER NOT NULL UNIQUE REFERENCES legal_decisions(id),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    actor_age INTEGER NOT NULL CHECK(actor_age>=18),
    actor_role TEXT NOT NULL CHECK(actor_role IN ('judge','regulator','competition_regulator','labor_regulator','gov_official')),
    policy TEXT NOT NULL CHECK(policy='disinterested_estate_adjudication_v1'),
    estate_frontier INTEGER NOT NULL CHECK(estate_frontier>=0),
    administration_frontier INTEGER NOT NULL CHECK(administration_frontier>=0),
    stewardship_frontier INTEGER NOT NULL CHECK(stewardship_frontier>=0),
    counsel_response_frontier INTEGER NOT NULL DEFAULT 0 CHECK(counsel_response_frontier>=0),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TABLE estate_administrations (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    administrator_agent_id INTEGER REFERENCES agents(id),
    region_id INTEGER REFERENCES regions(id),
    authority_role TEXT CHECK(authority_role='gov_official'),
    actor_age INTEGER CHECK(actor_age>=18),
    policy TEXT NOT NULL CHECK(policy='regional_public_trustee_v1'),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK((administrator_agent_id IS NULL AND authority_role IS NULL AND actor_age IS NULL) OR
          (administrator_agent_id IS NOT NULL AND region_id IS NOT NULL AND authority_role IS NOT NULL AND actor_age IS NOT NULL))
);
CREATE INDEX ix_estate_administration_case ON estate_administrations(estate_id,id);
CREATE TABLE estate_administration_ends (
    id INTEGER PRIMARY KEY,
    administration_id INTEGER NOT NULL UNIQUE REFERENCES estate_administrations(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    reason TEXT NOT NULL CHECK(reason IN ('private_representative','assets_disposed','authority_lost','candidate_available')),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TRIGGER estate_administration_one_current BEFORE INSERT ON estate_administrations
WHEN EXISTS(SELECT 1 FROM estate_administrations a WHERE a.estate_id=NEW.estate_id
            AND NOT EXISTS(SELECT 1 FROM estate_administration_ends e WHERE e.administration_id=a.id))
BEGIN SELECT RAISE(ABORT,'estate already has a current administration disposition'); END;
CREATE TABLE estate_project_custody (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    interest_lot_id INTEGER NOT NULL UNIQUE REFERENCES project_interest_lots(id),
    opened_tick INTEGER NOT NULL CHECK(opened_tick>=0),
    origin TEXT NOT NULL CHECK(origin IN ('opening','inheritance')),
    policy TEXT NOT NULL CHECK(policy='known_claims_then_residual_v1')
);
CREATE INDEX ix_estate_project_custody ON estate_project_custody(estate_id,id);
CREATE TABLE estate_project_releases (
    id INTEGER PRIMARY KEY,
    custody_id INTEGER NOT NULL UNIQUE REFERENCES estate_project_custody(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    disposition TEXT NOT NULL CHECK(disposition IN ('distributed','cancelled','sold')),
    cancellation_event_id INTEGER REFERENCES events(id),
    transaction_frontier INTEGER NOT NULL CHECK(transaction_frontier>=0),
    receipt_frontier INTEGER NOT NULL CHECK(receipt_frontier>=0),
    claim_frontier INTEGER NOT NULL CHECK(claim_frontier>=0),
    claim_release_frontier INTEGER NOT NULL CHECK(claim_release_frontier>=0),
    reserve_frontier INTEGER NOT NULL CHECK(reserve_frontier>=0),
    resolution_frontier INTEGER NOT NULL CHECK(resolution_frontier>=0),
    CHECK((disposition='cancelled')=(cancellation_event_id IS NOT NULL))
);
CREATE TABLE estate_property_bids (
    id INTEGER PRIMARY KEY,
    custody_id INTEGER NOT NULL REFERENCES estate_project_custody(id),
    buyer_agent_id INTEGER NOT NULL REFERENCES agents(id),
    buyer_account_id INTEGER NOT NULL REFERENCES accounts(id),
    buyer_age INTEGER NOT NULL CHECK(buyer_age>=18),
    created_tick INTEGER NOT NULL CHECK(created_tick>=0),
    expires_tick INTEGER NOT NULL CHECK(expires_tick>created_tick AND expires_tick<=created_tick+30),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0 AND amount_cents<=1000000000000),
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    UNIQUE(buyer_agent_id,request_key)
);
CREATE INDEX ix_estate_property_bid_custody ON estate_property_bids(custody_id,created_tick,id);
CREATE TABLE estate_property_bid_ends (
    id INTEGER PRIMARY KEY,
    bid_id INTEGER NOT NULL UNIQUE REFERENCES estate_property_bids(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    reason TEXT NOT NULL CHECK(reason IN ('accepted','withdrawn','expired','buyer_unavailable','custody_disposed','project_cancelled')),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TABLE estate_property_sales (
    id INTEGER PRIMARY KEY,
    bid_id INTEGER NOT NULL UNIQUE REFERENCES estate_property_bids(id),
    custody_id INTEGER NOT NULL UNIQUE REFERENCES estate_project_custody(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    successor_lot_id INTEGER NOT NULL UNIQUE REFERENCES project_interest_lots(id),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    authority_json TEXT NOT NULL CHECK(json_valid(authority_json)),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TABLE estate_security_lots (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    firm_id INTEGER NOT NULL REFERENCES firms(id),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    qty INTEGER NOT NULL CHECK(qty>0),
    source_item_id INTEGER UNIQUE REFERENCES estate_items(id),
    source_transfer_id INTEGER UNIQUE REFERENCES estate_share_transfers(id),
    policy TEXT NOT NULL CHECK(policy='known_claims_then_residual_v1'),
    CHECK((source_item_id IS NOT NULL)+(source_transfer_id IS NOT NULL)=1)
);
CREATE INDEX ix_estate_security_position ON estate_security_lots(estate_id,firm_id,id);
CREATE TABLE estate_security_releases (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL UNIQUE REFERENCES estate_security_lots(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    qty INTEGER NOT NULL CHECK(qty>=0),
    distribution_key TEXT,
    transaction_frontier INTEGER NOT NULL CHECK(transaction_frontier>=0),
    receipt_frontier INTEGER NOT NULL CHECK(receipt_frontier>=0),
    claim_frontier INTEGER NOT NULL CHECK(claim_frontier>=0),
    claim_release_frontier INTEGER NOT NULL CHECK(claim_release_frontier>=0),
    reserve_frontier INTEGER NOT NULL CHECK(reserve_frontier>=0),
    resolution_frontier INTEGER NOT NULL CHECK(resolution_frontier>=0),
    CHECK((qty=0 AND distribution_key IS NULL) OR (qty>0 AND distribution_key IS NOT NULL))
);
CREATE TABLE estate_security_orders (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    beneficiary_id INTEGER REFERENCES agents(id),
    guardian_id INTEGER REFERENCES guardianships(id),
    administration_id INTEGER REFERENCES estate_administrations(id),
    administration_end_frontier INTEGER NOT NULL DEFAULT 0 CHECK(administration_end_frontier>=0),
    actor_age INTEGER NOT NULL CHECK(actor_age>=18),
    beneficiary_age INTEGER CHECK(beneficiary_age>=0),
    estate_frontier_id INTEGER NOT NULL REFERENCES estate_cases(id),
    path_json TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    CHECK((administration_id IS NOT NULL AND beneficiary_id IS NULL AND guardian_id IS NULL AND beneficiary_age IS NULL) OR
          (administration_id IS NULL AND administration_end_frontier=0 AND beneficiary_id IS NOT NULL AND beneficiary_age IS NOT NULL AND
           ((guardian_id IS NULL AND actor_id=beneficiary_id AND beneficiary_age>=18) OR
            (guardian_id IS NOT NULL AND actor_id<>beneficiary_id AND beneficiary_age<18))))
);
CREATE TABLE estate_security_sales (
    id INTEGER PRIMARY KEY,
    trade_id INTEGER NOT NULL UNIQUE REFERENCES trades(id),
    authorization_id INTEGER NOT NULL REFERENCES estate_security_orders(id),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    buyer_account_id INTEGER NOT NULL REFERENCES accounts(id)
);
CREATE TABLE estate_security_sale_lots (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES estate_security_sales(id),
    lot_id INTEGER NOT NULL REFERENCES estate_security_lots(id),
    qty INTEGER NOT NULL CHECK(qty>0),
    UNIQUE(sale_id,lot_id)
);
CREATE TABLE estate_unlisted_bids (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES estate_security_lots(id),
    qty INTEGER NOT NULL CHECK(qty>0 AND qty<=1000000000000),
    buyer_agent_id INTEGER NOT NULL REFERENCES agents(id),
    buyer_account_id INTEGER NOT NULL REFERENCES accounts(id),
    buyer_age INTEGER NOT NULL CHECK(buyer_age>=18),
    listed_sale_frontier INTEGER NOT NULL CHECK(listed_sale_frontier>=0),
    created_tick INTEGER NOT NULL CHECK(created_tick>=0),
    expires_tick INTEGER NOT NULL CHECK(expires_tick>created_tick AND expires_tick<=created_tick+30),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0 AND amount_cents<=1000000000000),
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    UNIQUE(buyer_agent_id,request_key)
);
CREATE INDEX ix_estate_unlisted_bid_lot ON estate_unlisted_bids(lot_id,id);
CREATE TABLE estate_unlisted_bid_ends (
    id INTEGER PRIMARY KEY,
    bid_id INTEGER NOT NULL UNIQUE REFERENCES estate_unlisted_bids(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    reason TEXT NOT NULL CHECK(reason IN ('accepted','withdrawn','expired','buyer_unavailable','lot_disposed','lot_quantity_changed','issuer_status_changed')),
    issuer_status TEXT NOT NULL CHECK(length(issuer_status)>0),
    listed_sale_frontier INTEGER NOT NULL CHECK(listed_sale_frontier>=0),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK(reason<>'issuer_status_changed' OR issuer_status<>'private')
);
CREATE TABLE estate_unlisted_sales (
    id INTEGER PRIMARY KEY,
    bid_id INTEGER NOT NULL UNIQUE REFERENCES estate_unlisted_bids(id),
    lot_id INTEGER NOT NULL UNIQUE REFERENCES estate_security_lots(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    qty INTEGER NOT NULL CHECK(qty>0),
    actor_id INTEGER NOT NULL REFERENCES agents(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    movement_id INTEGER NOT NULL UNIQUE REFERENCES share_movements(id),
    listed_sale_frontier INTEGER NOT NULL CHECK(listed_sale_frontier>=0),
    authority_json TEXT NOT NULL CHECK(json_valid(authority_json)),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id)
);
CREATE TRIGGER estate_unlisted_movement_immutable BEFORE UPDATE ON share_movements
WHEN OLD.movement_type='estate_unlisted_sale' OR NEW.movement_type='estate_unlisted_sale'
BEGIN SELECT RAISE(ABORT,'private estate share movement is immutable'); END;
CREATE TRIGGER estate_unlisted_movement_no_delete BEFORE DELETE ON share_movements
WHEN OLD.movement_type='estate_unlisted_sale'
BEGIN SELECT RAISE(ABORT,'private estate share movement is permanent'); END;
-- Keep every prior officeholder and vote reference. Only an occupied seat is
-- unique; the old (chamber,seat_number,active) key allowed one former holder.
ALTER TABLE legislators RENAME TO legislators_schema24;
CREATE TABLE legislators (
    id INTEGER PRIMARY KEY,
    agent_id INTEGER NOT NULL UNIQUE,
    chamber TEXT NOT NULL,
    seat_number INTEGER NOT NULL,
    party_id INTEGER NOT NULL,
    term_start_tick INTEGER NOT NULL,
    term_end_tick INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO legislators SELECT * FROM legislators_schema24 ORDER BY id;
DROP TABLE legislators_schema24;
CREATE INDEX ix_legislators_chamber ON legislators(chamber,active);
CREATE UNIQUE INDEX ix_occupied_legislative_seat ON legislators(chamber,seat_number) WHERE active=1;
CREATE TABLE legal_wage_scopes (
    id INTEGER PRIMARY KEY,
    matter_id INTEGER NOT NULL REFERENCES legal_matters(id),
    claim_id INTEGER NOT NULL REFERENCES wage_claims(id),
    holder_id INTEGER NOT NULL REFERENCES wage_claim_holders(id),
    registered_tick INTEGER NOT NULL CHECK(registered_tick>=0),
    through_accrual_id INTEGER NOT NULL REFERENCES wage_accruals(id),
    start_cents INTEGER NOT NULL CHECK(start_cents>=0),
    end_cents INTEGER NOT NULL CHECK(end_cents>start_cents),
    currency_code TEXT NOT NULL,
    UNIQUE(matter_id,claim_id)
);
CREATE INDEX ix_legal_wage_scope_claim ON legal_wage_scopes(claim_id,matter_id);
CREATE TABLE legal_wage_awards (
    id INTEGER PRIMARY KEY,
    award_id INTEGER NOT NULL UNIQUE REFERENCES legal_awards(id),
    payable_account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    receivable_account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    recognition_transaction_id INTEGER UNIQUE REFERENCES transactions(id)
);
CREATE TABLE wage_claim_novations (
    id INTEGER PRIMARY KEY,
    award_id INTEGER NOT NULL REFERENCES legal_awards(id),
    scope_id INTEGER NOT NULL UNIQUE REFERENCES legal_wage_scopes(id),
    claim_id INTEGER NOT NULL REFERENCES wage_claims(id),
    prior_paid_cents INTEGER NOT NULL CHECK(prior_paid_cents>=0),
    prior_written_off_cents INTEGER NOT NULL DEFAULT 0 CHECK(prior_written_off_cents>=0),
    removed_cents INTEGER NOT NULL CHECK(removed_cents>=0),
    transaction_id INTEGER REFERENCES transactions(id),
    CHECK(removed_cents=0 OR transaction_id IS NOT NULL),
    UNIQUE(award_id,claim_id)
);
CREATE INDEX ix_wage_novation_claim ON wage_claim_novations(claim_id,id);
CREATE TABLE legal_award_losses (
    id INTEGER PRIMARY KEY,
    award_id INTEGER NOT NULL UNIQUE REFERENCES legal_awards(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    reason TEXT NOT NULL CHECK(reason='firm_bankruptcy'),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    transaction_id INTEGER UNIQUE REFERENCES transactions(id)
);
CREATE TABLE estate_legal_reserves (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    matter_id INTEGER NOT NULL UNIQUE REFERENCES legal_matters(id),
    registered_tick INTEGER NOT NULL CHECK(registered_tick>=0),
    registered_after_receipt_id INTEGER NOT NULL CHECK(registered_after_receipt_id>=0),
    currency_code TEXT NOT NULL,
    requested_cents INTEGER NOT NULL CHECK(requested_cents>0),
    prior_paid_cents INTEGER NOT NULL CHECK(prior_paid_cents>=0),
    reserve_limit_cents INTEGER NOT NULL CHECK(reserve_limit_cents=MAX(0,requested_cents-prior_paid_cents)),
    escrow_account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id)
);
CREATE INDEX ix_estate_reserve_case ON estate_legal_reserves(estate_id,currency_code,id);
CREATE TABLE estate_reserve_obligations (
    id INTEGER PRIMARY KEY,
    reserve_id INTEGER NOT NULL REFERENCES estate_legal_reserves(id),
    obligation_id INTEGER NOT NULL REFERENCES obligations(id),
    protected_cents INTEGER NOT NULL CHECK(protected_cents>0),
    UNIQUE(reserve_id,obligation_id)
);
CREATE TABLE estate_reserve_resolutions (
    id INTEGER PRIMARY KEY,
    reserve_id INTEGER NOT NULL UNIQUE REFERENCES estate_legal_reserves(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    after_receipt_id INTEGER NOT NULL CHECK(after_receipt_id>=0),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    released_cents INTEGER NOT NULL CHECK(released_cents>=0),
    transaction_id INTEGER UNIQUE REFERENCES transactions(id),
    CHECK((released_cents=0 AND transaction_id IS NULL) OR (released_cents>0 AND transaction_id IS NOT NULL))
);
CREATE TABLE legal_awards (
    id INTEGER PRIMARY KEY,
    matter_id INTEGER NOT NULL UNIQUE REFERENCES legal_matters(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    basis TEXT NOT NULL CHECK(basis IN ('decision','settlement')),
    claimant_type TEXT NOT NULL,
    claimant_id INTEGER NOT NULL,
    respondent_type TEXT NOT NULL,
    respondent_id INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    awarded_cents INTEGER NOT NULL CHECK(awarded_cents>0),
    credited_cents INTEGER NOT NULL CHECK(credited_cents>=0 AND credited_cents<=awarded_cents),
    credited_loss_cents INTEGER NOT NULL DEFAULT 0 CHECK(credited_loss_cents>=0),
    source_account_id INTEGER REFERENCES accounts(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    CHECK(credited_cents+credited_loss_cents<=awarded_cents)
);
CREATE INDEX ix_legal_award_respondent ON legal_awards(respondent_type,respondent_id,id);
CREATE TABLE legal_award_obligations (
    id INTEGER PRIMARY KEY,
    award_id INTEGER NOT NULL REFERENCES legal_awards(id),
    obligation_id INTEGER NOT NULL UNIQUE REFERENCES obligations(id),
    original_amount_cents INTEGER NOT NULL CHECK(original_amount_cents>0),
    prior_paid_cents INTEGER NOT NULL CHECK(prior_paid_cents>=0 AND prior_paid_cents<=original_amount_cents),
    UNIQUE(award_id,obligation_id)
);
CREATE TABLE legal_award_payments (
    id INTEGER PRIMARY KEY,
    award_id INTEGER NOT NULL REFERENCES legal_awards(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(tax_cents>=0 AND tax_cents<=amount_cents),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    estate_disbursement_id INTEGER UNIQUE REFERENCES estate_disbursements(id)
);
CREATE INDEX ix_legal_award_payment ON legal_award_payments(award_id,id);
CREATE TABLE estate_claim_releases (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES estate_claims(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    after_receipt_id INTEGER NOT NULL CHECK(after_receipt_id>=0),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    award_id INTEGER REFERENCES legal_awards(id),
    reason TEXT NOT NULL CHECK(reason IN ('adjudicated','contract_terminated','contract_expired')),
    CHECK((reason='adjudicated' AND award_id IS NOT NULL) OR (reason IN ('contract_terminated','contract_expired') AND award_id IS NULL))
);
CREATE UNIQUE INDEX ix_estate_claim_release ON estate_claim_releases(claim_id,COALESCE(award_id,0),reason);
CREATE TABLE project_interest_lots (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES construction_projects(id),
    agent_id INTEGER REFERENCES agents(id),
    numerator TEXT NOT NULL CHECK(length(numerator)>0 AND numerator NOT GLOB '*[^0-9]*' AND substr(numerator,1,1)<>'0'),
    denominator TEXT NOT NULL CHECK(length(denominator)>0 AND denominator NOT GLOB '*[^0-9]*' AND substr(denominator,1,1)<>'0'),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    ended_tick INTEGER CHECK(ended_tick>=started_tick),
    prior_lot_id INTEGER REFERENCES project_interest_lots(id),
    estate_id INTEGER REFERENCES estate_cases(id),
    CHECK((prior_lot_id IS NULL AND estate_id IS NULL) OR (prior_lot_id IS NOT NULL AND estate_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_project_interest_root ON project_interest_lots(project_id) WHERE prior_lot_id IS NULL;
CREATE UNIQUE INDEX ix_project_interest_successor ON project_interest_lots(prior_lot_id,COALESCE(agent_id,0));
CREATE INDEX ix_project_interests_at ON project_interest_lots(project_id,started_tick,ended_tick);
CREATE INDEX ix_person_project_interests ON project_interest_lots(agent_id,ended_tick,project_id);
CREATE TRIGGER project_interest_terms_immutable BEFORE UPDATE OF id,project_id,agent_id,numerator,denominator,started_tick,prior_lot_id,estate_id ON project_interest_lots
BEGIN SELECT RAISE(ABORT,'project beneficial interest is immutable'); END;
CREATE TRIGGER project_interest_end_once BEFORE UPDATE OF ended_tick ON project_interest_lots
WHEN OLD.ended_tick IS NOT NULL OR NEW.ended_tick IS NULL
BEGIN SELECT RAISE(ABORT,'project beneficial interest ending is permanent'); END;
CREATE TRIGGER project_interest_no_delete BEFORE DELETE ON project_interest_lots
BEGIN SELECT RAISE(ABORT,'project beneficial interest history is permanent'); END;
CREATE TABLE project_stewardships (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES construction_projects(id),
    steward_agent_id INTEGER REFERENCES agents(id),
    capacity TEXT NOT NULL CHECK(capacity IN ('owner','guardian','estate','administrator','vacant')),
    beneficiary_id INTEGER REFERENCES agents(id),
    estate_id INTEGER REFERENCES estate_cases(id),
    administration_id INTEGER REFERENCES estate_administrations(id),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    ended_tick INTEGER CHECK(ended_tick>=started_tick),
    CHECK((capacity='vacant' AND steward_agent_id IS NULL) OR (capacity<>'vacant' AND steward_agent_id IS NOT NULL)),
    CHECK((capacity IN ('guardian','estate') AND beneficiary_id IS NOT NULL) OR (capacity NOT IN ('guardian','estate') AND beneficiary_id IS NULL)),
    CHECK((capacity IN ('estate','administrator'))=(estate_id IS NOT NULL)),
    CHECK((capacity='administrator')=(administration_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_current_project_steward ON project_stewardships(project_id) WHERE ended_tick IS NULL;
CREATE INDEX ix_project_stewards_at ON project_stewardships(project_id,started_tick,ended_tick);
CREATE INDEX ix_project_steward_person ON project_stewardships(steward_agent_id,ended_tick,project_id);
CREATE TRIGGER project_steward_terms_immutable BEFORE UPDATE OF id,project_id,steward_agent_id,capacity,beneficiary_id,estate_id,administration_id,started_tick ON project_stewardships
BEGIN SELECT RAISE(ABORT,'project stewardship identity is immutable'); END;
CREATE TRIGGER project_steward_end_once BEFORE UPDATE OF ended_tick ON project_stewardships
WHEN OLD.ended_tick IS NOT NULL OR NEW.ended_tick IS NULL
BEGIN SELECT RAISE(ABORT,'project stewardship ending is permanent'); END;
CREATE TRIGGER project_steward_no_delete BEFORE DELETE ON project_stewardships
BEGIN SELECT RAISE(ABORT,'project stewardship history is permanent'); END;
CREATE TABLE estate_cases (
    id INTEGER PRIMARY KEY,
    deceased_agent_id INTEGER NOT NULL UNIQUE REFERENCES agents(id),
    opened_tick INTEGER NOT NULL CHECK(opened_tick>=0),
    policy TEXT NOT NULL CHECK(policy='family_equal_deficit_then_bank_then_contract_v1'),
    distribution_finality_policy TEXT NOT NULL DEFAULT 'prospective_receipts_no_clawback_v1'
        CHECK(distribution_finality_policy='prospective_receipts_no_clawback_v1'),
    beneficiary_count INTEGER NOT NULL CHECK(beneficiary_count>0),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count>=0),
    claim_count INTEGER NOT NULL DEFAULT 0 CHECK(claim_count>=0),
    completed_event_id INTEGER UNIQUE REFERENCES events(id)
);
CREATE TABLE estate_beneficiaries (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    agent_id INTEGER REFERENCES agents(id),
    weight INTEGER NOT NULL CHECK(weight>0),
    basis TEXT NOT NULL CHECK(basis IN ('partner','child','parent','social_tie','escheat')),
    CHECK((basis='escheat' AND agent_id IS NULL) OR (basis<>'escheat' AND agent_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_estate_beneficiary ON estate_beneficiaries(estate_id,COALESCE(agent_id,0));
CREATE TABLE estate_items (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    kind TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('distributed','retained','extinguished','creditor_claim','unresolved_deficit')),
    amount INTEGER,
    currency_code TEXT,
    snapshot_json TEXT NOT NULL,
    UNIQUE(estate_id,kind,source_id)
);
CREATE TABLE estate_claims (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    kind TEXT NOT NULL CHECK(kind IN ('bank_principal','contract_payment','legal_award')),
    source_id INTEGER NOT NULL,
    registered_tick INTEGER NOT NULL DEFAULT 0 CHECK(registered_tick>=0),
    registered_after_receipt_id INTEGER NOT NULL DEFAULT 0 CHECK(registered_after_receipt_id>=0),
    is_opening INTEGER NOT NULL DEFAULT 1 CHECK(is_opening IN (0,1)),
    creditor_type TEXT NOT NULL,
    creditor_id INTEGER NOT NULL,
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    currency_code TEXT NOT NULL,
    principal_cents INTEGER NOT NULL CHECK(principal_cents>0),
    equity_account_id INTEGER REFERENCES accounts(id),
    loss_account_id INTEGER REFERENCES accounts(id),
    CHECK((kind='bank_principal' AND creditor_type='bank' AND equity_account_id IS NOT NULL AND loss_account_id IS NOT NULL)
       OR (kind IN ('contract_payment','legal_award') AND equity_account_id IS NULL AND loss_account_id IS NULL)),
    UNIQUE(kind,source_id)
);
CREATE INDEX ix_estate_claim_priority ON estate_claims(estate_id,currency_code,kind,source_id);
CREATE TABLE estate_claim_losses (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL UNIQUE REFERENCES estate_claims(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id)
);
CREATE TABLE estate_receipts (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES estate_cases(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    source_account_id INTEGER NOT NULL REFERENCES accounts(id),
    origin_transaction_id INTEGER REFERENCES transactions(id),
    currency_code TEXT NOT NULL,
    received_cents INTEGER NOT NULL CHECK(received_cents>0),
    post_balance_cents INTEGER NOT NULL,
    available_cents INTEGER NOT NULL CHECK(available_cents=MIN(received_cents,MAX(0,post_balance_cents)))
);
CREATE UNIQUE INDEX ix_estate_receipt_origin ON estate_receipts(source_account_id,COALESCE(origin_transaction_id,0));
CREATE INDEX ix_estate_receipt_case ON estate_receipts(estate_id,tick,id);
CREATE TABLE estate_cash_offsets (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES estate_receipts(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    negative_before_cents INTEGER NOT NULL CHECK(negative_before_cents<0),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0 AND amount_cents<=-negative_before_cents),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id)
);
CREATE UNIQUE INDEX ix_estate_cash_offset_target ON estate_cash_offsets(receipt_id,destination_account_id);
CREATE INDEX ix_estate_cash_offset_wallet ON estate_cash_offsets(destination_account_id,id);
CREATE TABLE estate_disbursements (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES estate_receipts(id),
    claim_id INTEGER REFERENCES estate_claims(id),
    beneficiary_id INTEGER REFERENCES estate_beneficiaries(id),
    reserve_id INTEGER REFERENCES estate_legal_reserves(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    recovery_transaction_id INTEGER UNIQUE REFERENCES transactions(id),
    CHECK((claim_id IS NOT NULL)+(beneficiary_id IS NOT NULL)+(reserve_id IS NOT NULL)=1),
    CHECK(recovery_transaction_id IS NULL OR claim_id IS NOT NULL)
);
CREATE INDEX ix_estate_disbursement_claim ON estate_disbursements(claim_id,id);
CREATE INDEX ix_estate_disbursement_receipt ON estate_disbursements(receipt_id,id);
CREATE UNIQUE INDEX ix_estate_receipt_claim ON estate_disbursements(receipt_id,claim_id) WHERE claim_id IS NOT NULL;
CREATE UNIQUE INDEX ix_estate_receipt_beneficiary ON estate_disbursements(receipt_id,beneficiary_id) WHERE beneficiary_id IS NOT NULL;
CREATE UNIQUE INDEX ix_estate_receipt_reserve ON estate_disbursements(receipt_id,reserve_id) WHERE reserve_id IS NOT NULL;
CREATE TRIGGER estate_case_terms_immutable BEFORE UPDATE OF id,deceased_agent_id,opened_tick,policy,distribution_finality_policy,beneficiary_count ON estate_cases
BEGIN SELECT RAISE(ABORT,'estate case identity is immutable'); END;
CREATE TRIGGER estate_case_complete_once BEFORE UPDATE OF item_count,claim_count,completed_event_id ON estate_cases
WHEN OLD.completed_event_id IS NOT NULL OR NEW.completed_event_id IS NULL
BEGIN SELECT RAISE(ABORT,'estate opening inventory is permanent'); END;
CREATE TRIGGER estate_case_no_delete BEFORE DELETE ON estate_cases
BEGIN SELECT RAISE(ABORT,'estate case is permanent'); END;
CREATE TABLE firm_stewardships (
    id INTEGER PRIMARY KEY,
    firm_id INTEGER NOT NULL REFERENCES firms(id),
    steward_agent_id INTEGER REFERENCES agents(id),
    capacity TEXT NOT NULL CHECK(capacity IN ('founder','shareholder','guardian','estate','employee','vacant')),
    beneficiary_id INTEGER REFERENCES agents(id),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    ended_tick INTEGER CHECK(ended_tick>=started_tick),
    death_event_id INTEGER REFERENCES events(id),
    recorded_event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    CHECK((capacity='guardian' AND beneficiary_id IS NOT NULL AND steward_agent_id IS NOT NULL)
       OR (capacity<>'guardian' AND beneficiary_id IS NULL)),
    CHECK((capacity='vacant' AND steward_agent_id IS NULL) OR capacity='founder'
       OR (capacity<>'vacant' AND steward_agent_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_current_firm_steward ON firm_stewardships(firm_id) WHERE ended_tick IS NULL;
CREATE INDEX ix_firm_steward_history ON firm_stewardships(firm_id,started_tick,ended_tick);
CREATE INDEX ix_steward_firms ON firm_stewardships(steward_agent_id,ended_tick,firm_id);
CREATE TRIGGER firm_steward_terms_immutable BEFORE UPDATE OF
    id,firm_id,steward_agent_id,capacity,beneficiary_id,started_tick,death_event_id,recorded_event_id ON firm_stewardships
BEGIN SELECT RAISE(ABORT,'business stewardship identity is immutable'); END;
CREATE TRIGGER firm_steward_end_once BEFORE UPDATE OF ended_tick ON firm_stewardships
WHEN OLD.ended_tick IS NOT NULL OR NEW.ended_tick IS NULL
BEGIN SELECT RAISE(ABORT,'business stewardship ending is permanent'); END;
CREATE TRIGGER firm_steward_no_delete BEFORE DELETE ON firm_stewardships
BEGIN SELECT RAISE(ABORT,'business stewardship history is permanent'); END;
CREATE VIEW firm_operations AS
SELECT f.*, CASE WHEN s.id IS NULL THEN f.founder_agent_id ELSE s.steward_agent_id END AS operator_agent_id,
       COALESCE(s.capacity,'founder') AS operator_capacity, s.beneficiary_id AS operator_beneficiary_id
FROM firms f LEFT JOIN firm_stewardships s ON s.firm_id=f.id AND s.ended_tick IS NULL;
CREATE TABLE estate_share_transfers (
    id INTEGER PRIMARY KEY,
    deceased_agent_id INTEGER NOT NULL REFERENCES agents(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    firm_id INTEGER NOT NULL REFERENCES firms(id),
    beneficiary_type TEXT NOT NULL CHECK(beneficiary_type IN ('agent','system')),
    beneficiary_id INTEGER REFERENCES agents(id),
    distribution_key TEXT NOT NULL CHECK(length(distribution_key) BETWEEN 1 AND 96),
    movement_id INTEGER NOT NULL UNIQUE REFERENCES share_movements(id),
    former_qty INTEGER NOT NULL CHECK(former_qty>0),
    qty INTEGER NOT NULL CHECK(qty>0 AND qty<=former_qty),
    CHECK((beneficiary_type='agent' AND beneficiary_id IS NOT NULL AND beneficiary_id<>deceased_agent_id)
       OR (beneficiary_type='system' AND beneficiary_id IS NULL))
);
CREATE UNIQUE INDEX ix_estate_share_recipient ON estate_share_transfers(deceased_agent_id,firm_id,distribution_key,beneficiary_type,COALESCE(beneficiary_id,0));
CREATE INDEX ix_estate_share_firm ON estate_share_transfers(firm_id,tick);
CREATE TRIGGER estate_share_transfer_immutable BEFORE UPDATE ON estate_share_transfers
BEGIN SELECT RAISE(ABORT,'inherited share receipt is immutable'); END;
CREATE TRIGGER estate_share_transfer_no_delete BEFORE DELETE ON estate_share_transfers
BEGIN SELECT RAISE(ABORT,'inherited share receipt is permanent'); END;
"""

for _table in (*ESTATE_TABLES[1:], *AWARD_TABLES, *DISPUTE_TABLES, *SECURITY_TABLES, *PROPERTY_CUSTODY_TABLES, *ADMINISTRATION_TABLES, *AUTHORITY_TABLES, *REPRESENTATION_TABLES):
    SQL += f"""
CREATE TRIGGER {_table}_immutable BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT,'estate evidence is immutable'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT,'estate evidence is permanent'); END;
"""


def verify(conn):
    objects = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}
    required = {"firm_stewardships", "firm_operations", "ix_current_firm_steward",
        "ix_firm_steward_history", "ix_steward_firms", "firm_steward_terms_immutable",
        "firm_steward_end_once", "firm_steward_no_delete"}
    required |= set(SECURITY_TABLES) | {"ix_estate_security_position", "ix_estate_unlisted_bid_lot",
        "estate_unlisted_movement_immutable", "estate_unlisted_movement_no_delete"}
    required |= {f"{table}_{suffix}" for table in SECURITY_TABLES for suffix in ("immutable", "no_delete")}
    required |= {"legislators", "ix_legislators_chamber", "ix_occupied_legislative_seat"}
    required |= {"estate_share_transfers", "ix_estate_share_recipient", "ix_estate_share_firm",
                 "estate_share_transfer_immutable", "estate_share_transfer_no_delete"}
    required |= set(ESTATE_TABLES) | {"ix_estate_beneficiary", "ix_estate_claim_priority",
        "ix_estate_receipt_origin", "ix_estate_receipt_case", "ix_estate_disbursement_claim",
        "ix_estate_disbursement_receipt", "ix_estate_receipt_claim", "ix_estate_receipt_beneficiary", "estate_case_terms_immutable",
        "estate_case_complete_once", "estate_case_no_delete", "ix_estate_cash_offset_target", "ix_estate_cash_offset_wallet"}
    required |= {f"{table}_{suffix}" for table in ESTATE_TABLES[1:]
                 for suffix in ("immutable", "no_delete")}
    required |= set(AWARD_TABLES) | {"ix_legal_award_respondent", "ix_legal_award_payment", "ix_estate_claim_release",
                                    "ix_legal_wage_scope_claim", "ix_wage_novation_claim"}
    required |= {f"{table}_{suffix}" for table in AWARD_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(DISPUTE_TABLES) | {"ix_estate_reserve_case", "ix_estate_receipt_reserve"}
    required |= {f"{table}_{suffix}" for table in DISPUTE_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(PROPERTY_CUSTODY_TABLES) | {"ix_estate_project_custody", "ix_estate_property_bid_custody"}
    required |= {f"{table}_{suffix}" for table in PROPERTY_CUSTODY_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(ADMINISTRATION_TABLES) | {"ix_estate_administration_case", "estate_administration_one_current"}
    required |= {f"{table}_{suffix}" for table in ADMINISTRATION_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(AUTHORITY_TABLES)
    required |= {f"{table}_{suffix}" for table in AUTHORITY_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(REPRESENTATION_TABLES) | {"ix_legal_action_authority_matter", "ix_legal_claim_authority", "ix_legal_settlement_authority",
                                          "ix_legal_counsel_matter", "legal_counsel_one_current"}
    required |= {f"{table}_{suffix}" for table in REPRESENTATION_TABLES for suffix in ("immutable", "no_delete")}
    required |= set(PROJECT_TABLES) | {"ix_project_interest_root", "ix_project_interest_successor",
        "ix_project_interests_at", "ix_person_project_interests", "project_interest_terms_immutable",
        "project_interest_end_once", "project_interest_no_delete", "ix_current_project_steward",
        "ix_project_stewards_at", "ix_project_steward_person", "project_steward_terms_immutable",
        "project_steward_end_once", "project_steward_no_delete"}
    if not required <= objects:
        raise RuntimeError("business stewardship history is missing")
