/**
 * Formatting helpers for the token-based UI kit.
 *
 * Unit convention (one, everywhere): <value> <unit>, the unit rendered as its own
 * quieter span. Headline figures are never abbreviated and never gain decimals
 * they were not given.
 */

export type Direction = "up" | "down" | "flat";
export type Judgement = "pos" | "neg" | "caution" | "neutral" | "hold";

const DIRECTION_GLYPH: Record<Direction, string> = {
  up: "▲",
  down: "▼",
  flat: "–",
};

export function directionGlyph(direction: Direction): string {
  return DIRECTION_GLYPH[direction];
}

/**
 * SALIENCE TRACKS EXCEPTIONALITY, NOT MOVEMENT.
 *
 * A one-tick delta is the most routine event this surface has: something moved,
 * as it does every tick. Spending chroma on it — a green triangle on a +160.72
 * GDP tick — is what left the screen's genuinely alarming figure, a six-figure
 * negative treasury, as its flattest. Only an ADVERSE reading takes ink here;
 * welcome and neutral movements keep the direction glyph and the quiet tier, and
 * the number itself is unsigned either way because the glyph already carries the
 * sign. This is the same rule the ledgers keep, applied to the same palette.
 */
const ADVERSE_JUDGEMENTS = new Set<Judgement>(["neg", "caution"]);

export function isAdverse(judgement: Judgement): boolean {
  return ADVERSE_JUDGEMENTS.has(judgement);
}

/**
 * A formatted figure split at its decimal separator so a column can align on the
 * point rather than on the cell edge.
 *
 * Right-aligning a column that mixes 0dp and 2dp promises a spine and then
 * breaks it: `-750,481.00`, `1,200` and `39` share a right edge and no two
 * decimal points line up. Reserving a fixed slot for the fraction puts the point
 * itself on one x for the whole column, and a value that has no fraction keeps
 * its slot EMPTY rather than gaining `.00` digits it was never given.
 *
 * Grouping is en-US throughout (see `decimal`), so the last "." in a formatted
 * figure is always the decimal separator and never a thousands mark.
 */
export function splitDecimal(value: string): { whole: string; fraction: string } {
  const point = value.lastIndexOf(".");
  if (point < 0) return { whole: value, fraction: "" };
  return { whole: value.slice(0, point), fraction: value.slice(point) };
}

/** True only for values we actually received. Guards every "never render a zero
 *  we do not have" call site: 0 is real, null/undefined/NaN are not. */
export function received(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Narrow an unknown reading to a number we actually hold, or null. */
export function numberOr(value: unknown): number | null {
  return received(value) ? value : null;
}

export function count(value: unknown): string | null {
  return received(value) ? value.toLocaleString("en-US") : null;
}

export function decimal(value: unknown, digits: number): string | null {
  if (!received(value)) return null;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Cents to a plain major-unit figure. The currency code is passed separately as
 *  the unit, because in a three-currency world the unit is per-row data. */
export function fromCents(value: unknown, digits = 2): string | null {
  if (!received(value)) return null;
  return decimal(value / 100, digits);
}

export function percentFromFraction(value: unknown, digits = 2): string | null {
  if (!received(value)) return null;
  return decimal(value * 100, digits);
}

/** Latency, in the smallest honest unit. */
export function latencyText(ms: unknown): string | null {
  if (!received(ms)) return null;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * Bar length for a latency reading, as a percentage of the track.
 *
 * Linear length is actively misleading here: 93 ms and 13.3 s differ by more than
 * two orders of magnitude, and a linear encoding renders them at comparable
 * lengths only if the scale is broken. This is a base-10 log scale across a fixed
 * 1 ms – 30 s domain, and every meter that uses it prints "log scale" next to it.
 */
/* Domain chosen from measured readings on the live run, which span 2 ms
   (/api/run/status when the tick loop is idle) to about 66 s (/api/institutions
   while a heavy phase holds the server's event loop). A narrower ceiling clamps
   every bar to full during a stall and stops discriminating. */
export const LATENCY_FLOOR_MS = 1;
export const LATENCY_CEILING_MS = 60_000;

export function latencyBarFraction(ms: unknown): number {
  if (!received(ms) || ms <= 0) return 0;
  const clamped = Math.min(LATENCY_CEILING_MS, Math.max(LATENCY_FLOOR_MS, ms));
  const span = Math.log10(LATENCY_CEILING_MS) - Math.log10(LATENCY_FLOOR_MS);
  return (Math.log10(clamped) - Math.log10(LATENCY_FLOOR_MS)) / span;
}

/** Slow enough that a reader should expect to wait for it. */
export function isSlow(ms: unknown): boolean {
  return received(ms) && ms >= 1000;
}

/* ============================================================ kind codes == */

/**
 * THE EVENT-KIND CODE REGISTRY.
 *
 * Kinds are coded, not coloured: the channel has to scale past two hundred kinds
 * and a palette cannot. But a code system has to be DESIGNED, and the previous
 * one was not — anything it did not recognise fell through to `slice(0, 4)`, so
 * `civic_appointment_scheduled` printed CIVI, `claim_created` printed CLAI,
 * `ipo_bid_placed` printed IPOB and `model_numeric_narrative_redacted` printed
 * MODE. Those are not codes, they are corrupted labels, and nothing on the glyph
 * said so: MODE reads as the English word "mode" and CIVI is indistinguishable
 * from a genuine four-letter code like CONV or NEWS. Truncation that leaves no
 * mark is worse than truncation that does.
 *
 * Two rules replace it, and between them nothing is ever silently lossy:
 *
 *   1. EVERY KIND THE SYSTEM CAN EMIT HAS A DESIGNED CODE. The registry below is
 *      total over both vocabularies that exist: the distinct kinds committed by
 *      the reference run (read out of its event spine) and every kind literal
 *      the engine and world packages emit. Codes
 *      are hand-assigned, verified unique, and grouped by domain so related
 *      kinds share a stem and can be told apart at a glance rather than guessed:
 *      the six permit outcomes are PMAP/PMOK/PMNO/PMRF/PMTR/PMAB, the two
 *      information channels are IPUB and IEXP, the loan denials are LNDN, LNDC
 *      and LNDL. Where two kinds would have collided they are separated on
 *      purpose (`benefit_paid` BENP against `benefits_paid` BENS; `hired` HIRD
 *      against `job_offer_accepted` JOFA), never merged onto one glyph the way
 *      the old table merged three permit kinds onto PRMT.
 *
 *   2. AN UNREGISTERED KIND SAYS SO ON THE GLYPH. It is shortened to three
 *      letters and carries a trailing ellipsis — `CIV…`, never `CIVI` — so an
 *      abbreviation can never be mistaken for a code, and the coding is reported
 *      as inexact so the cell can be drawn in the quieter ink and say why on
 *      hover. A kind short enough to survive whole (`ipo`) is shown whole and
 *      reported exact, because that one is not lossy.
 */
const KIND_CODES: Record<string, string> = {
  /* -- isolated induced-value market fixtures -- */
  benchmark_inventory_endowment: "BMIN",
  benchmark_share_endowment: "BMSH",
  benchmark_contract: "BMCT",
  benchmark_purchase_intent: "BMPI",
  benchmark_book: "BMBK",
  benchmark_redemption: "BMRD",
  /* -- lifecycle and population -- */
  arrival: "ARIV",
  arrival_scheduled: "ARSC",
  birth: "BRTH",
  birthday: "BDAY",
  death: "DETH",
  estate_cash_settled: "ECAS",
  estate_case_opened: "EINV",
  estate_administration_started: "EADS",
  estate_administration_ended: "EADX",
  estate_property_bid_placed: "EPBP",
  estate_property_bid_ended: "EPBX",
  estate_property_sold: "EPSL",
  estate_security_order_placed: "ESOP",
  estate_unlisted_bid_placed: "EUBP",
  estate_unlisted_bid_ended: "EUBX",
  estate_unlisted_sold: "EUSL",
  business_steward_changed: "BSTW",
  business_stewardship_recorded: "BSRC",
  retirement: "RETR",
  retirement_job_search_withdrawn: "RJSW",
  retirement_savings_withdrawal: "RSWD",
  agent_migrated: "MIGR",
  population_residence_recorded: "PRES",
  population_movement_proposed: "PMPR",
  population_movement_assent: "PMAS",
  population_movement_closed: "PMCL",
  population_household_moved: "PHMV",
  population_authority_released: "PARE",
  population_commitment_ended: "PCEN",
  population_scenario_declared: "PSDE",
  population_scenario_input: "PSIN",
  employment_ended_for_departure: "EPDP",
  job_offer_ended_for_departure: "JODP",
  job_application_ended_for_departure: "JADP",
  migration_rejected_ineligible: "MIGX",
  migration_rejected_credit_exposure: "MIGC",
  agent_tier_changed: "TIER",
  persona_enriched: "PRSN",
  housing_cost: "HOUS",

  /* -- health and insurance -- */
  illness_onset: "ILLO",
  illness_critical: "ILLC",
  recovery: "RCVR",
  epidemic_started: "EPID",
  epidemic_ended: "EPIX",
  policy_bought: "PLCB",
  policy_lapsed: "PLCL",
  insurance_claim: "INSC",

  /* -- labour -- */
  job_posted: "JPST",
  job_application: "JAPP",
  job_offer_made: "JOFM",
  job_offer_accepted: "JOFA",
  job_offer_countered: "JOFC",
  job_offer_rejected: "JOFR",
  job_offer_expired_incompatible_currency: "JOFX",
  job_search_started: "JSRC",
  hired: "HIRD",
  fired: "FIRD",
  wage_paid: "WAGP",
  wage_earned: "EARN",
  wage_claim_closed: "WCLS",
  wage_claim_inherited: "WINH",
  wage_claim_written_off: "WOFF",
  legal_award_written_off: "LWOF",
  time_plan_submitted: "TIME",
  child_care_delivered: "CARE",
  wage_missed: "WAGM",
  wage_skipped_illness: "WAGI",
  skill_level_changed: "SKIL",
  skill_studied: "SKST",
  workforce_recovery_job_floor_enforced: "WFJF",

  /* -- firms, goods, production -- */
  company_founded: "CFND",
  production: "PROD",
  price_set: "PRIC",
  goods_sale: "SALE",
  order_placed: "ORDR",
  trade: "TRAD",
  bankruptcy: "BNKR",
  firm_disclosure_published: "FDIS",
  firm_scandal: "FSCD",
  merger_proposed: "MRGP",
  merger_notified: "MRGN",
  merger_reviewed: "MRGV",
  merger_closed: "MRGC",
  ip_registered: "IPRG",
  ip_licensed: "IPLC",
  commodity_shock: "CMDS",
  shock_fired: "SHOK",
  supply_recovery_recapitalized: "SRRC",
  supply_recovery_recapitalization_applied: "SRRA",
  quiet_day: "QDAY",

  /* -- capital markets and venture -- */
  ipo: "IPO",
  ipo_book_opened: "BOOK",
  ipo_bid_placed: "IBID",
  bootstrap_listing: "BLST",
  pitch_made: "PTCH",
  pitch_declined: "PTCD",
  due_diligence_completed: "DDIL",
  term_sheet_offered: "TSOF",
  term_sheet_accepted: "TSAC",
  funding_round_closed: "FUND",
  vc_funded: "VCFD",
  vc_writeoff: "VCWO",
  fx_order_placed: "FXOR",
  fx_trade: "FXTR",
  trade_shipment_created: "SHPC",
  trade_shipment_delivered: "SHPD",

  /* -- banking and credit -- */
  loan_application: "LNAP",
  loan_originated: "LNOR",
  loan_paid: "LNPD",
  loan_denied: "LNDN",
  loan_denied_currency: "LNDC",
  loan_denied_liquidity: "LNDL",
  loan_arrears: "LNAR",
  loan_default: "LNDF",
  interbank_loan: "IBLN",
  lolr_granted: "LLRG",
  lolr_denied: "LLRD",
  liquidity_support_requested: "LQSR",
  bank_failure: "BKFL",
  deposit_move: "DPMV",
  circuit_breaker: "CBRK",
  reconciliation_failure: "RCNF",
  policy_rate_set: "RATE",

  /* -- government and fiscal -- */
  benefit_paid: "BENP",
  benefits_paid: "BENS",
  election_held: "ELCT",
  federal_election_held: "FELC",
  bill_introduced: "BILI",
  bill_amended: "BILA",
  bill_enacted: "BILE",
  bill_vetoed: "BILV",
  policy_rule_change: "PRCH",
  policy_rule_effective: "PREF",
  lobbying_activity: "LOBA",
  lobbying_disclosed: "LOBD",
  public_statement: "PSTM",
  political_institutions_created: "POLI",
  institution_created: "INST",
  institution_task_assigned: "ITSK",
  agency_staff_appointed: "STAF",
  regions_initialized: "RGNS",
  genesis: "GNSS",

  /* -- civic city -- */
  civic_city_initialized: "CITY",
  civic_appointment_scheduled: "APTS",
  civic_appointment_attended: "APTA",
  civic_authorization_consumed: "AUTC",
  civic_authorization_expired: "AUTX",
  business_permit_applied: "PMAP",
  business_permit_approved: "PMOK",
  business_permit_denied: "PMNO",
  business_permit_referred: "PMRF",
  business_permit_case_transferred: "PMTR",
  business_permit_abandoned: "PMAB",

  /* -- construction economy -- */
  construction_project_proposed: "CPRO",
  construction_permit_submitted: "CPSB",
  construction_funding_contributed: "CFCT",
  construction_work_contributed: "CWCT",
  construction_project_cancelled: "CCAN",
  construction_project_completed: "CCMP",

  /* -- legal -- */
  claim_created: "CLAM",
  legal_matter_filed: "LMAT",
  legal_filing_submitted: "LFIL",
  legal_notice_issued: "LNOT",
  legal_decision_enforced: "LDEC",
  legal_decision_recused: "LDRC",
  legal_counsel_requested: "LCRQ",
  legal_counsel_responded: "LCRS",
  legal_counsel_ended: "LCEN",
  legal_decision_validation_failed: "LDVF",
  matter_settled: "MSTL",
  settlement_offered: "SOFF",
  obligation_breached: "OBBR",
  obligation_performed: "OBPF",
  contract_offered: "CTOF",
  contract_countered: "CTCO",
  contract_executed: "CTEX",
  contract_expired: "CTXP",
  contract_performed: "CTPF",
  contract_rejected: "CTRJ",

  /* -- information and cognition -- */
  belief_updated: "BELF",
  conversation: "CONV",
  information_published: "IPUB",
  information_exposed: "IEXP",
  news_published: "NEWS",
  rumor: "RUMR",
  slant_directive: "SLNT",
  model_numeric_narrative_redacted: "RDCT",
  action_rejected: "REJT",

  /* -- agent commons -- */
  commons_community_created: "COMC",
  commons_entry_published: "COMP",
  commons_entry_read: "COMR",
  commons_follow_changed: "COMF",
  commons_membership_joined: "COMJ",
  commons_moderation_applied: "COMM",
  commons_reaction_changed: "COMX",

  /* -- compute economy -- */
  compute_plan_changed: "CPUC",
  compute_plan_purchased: "CPUP",
  compute_plan_cancelled: "CPUX",
  compute_sponsorship_set: "CPUS",

  /* -- run operations and fixtures -- */
  checkpoint_failed: "CKPF",
  checkpoint_prune_failed: "CKPP",
  report_failed: "RPTF",
  behavioral_fixture_seeded: "BFIX",
  r21_calibration_applied: "R21C",
  r21_firm_size_sampled: "R21F",
  r21_household_sampled: "R21H",
};

/** The one glyph that means "this label is shorter than the thing it names". */
export const KIND_TRUNCATION_MARK = "…";

export type KindCoding = {
  /** What the cell prints. At most four characters. */
  code: string;
  /**
   * True when the code is the registry's designed code for this kind, or the
   * whole kind because it was short enough to survive. False when the kind is
   * unregistered and the code is therefore an abbreviation — which is exactly
   * when the mark is present and the cell drops to the quieter ink.
   */
  exact: boolean;
};

/** Every kind that carries a designed code, for tests and for tooling. */
export function codedKinds(): string[] {
  return Object.keys(KIND_CODES);
}

export function kindCoding(kind: string): KindCoding {
  const normalized = String(kind || "").trim().toLowerCase();
  const designed = KIND_CODES[normalized];
  if (designed) return { code: designed, exact: true };
  const letters = normalized.replace(/[^a-z0-9]/g, "");
  /* No kind at all is an absence, not an abbreviation: it takes the surface's
     absence glyph rather than a truncation mark it did not earn. */
  if (!letters) return { code: "—", exact: false };
  /* Short enough to be shown whole: nothing is lost, so nothing is marked. */
  if (letters.length <= 4) return { code: letters.toUpperCase(), exact: true };
  return { code: `${letters.slice(0, 3).toUpperCase()}${KIND_TRUNCATION_MARK}`, exact: false };
}

export function kindCode(kind: string): string {
  return kindCoding(kind).code;
}

export function titleCase(value: string): string {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

/**
 * A protocol token read as a sentence: `credit_officer` becomes "Credit officer".
 * Internal vocabulary is never the primary copy on this surface — the raw token
 * stays available on the element's title, where a reader who wants it can find it,
 * but it is not what the page says out loud.
 */
export function humanize(value: unknown): string {
  const words = String(value ?? "").replaceAll("_", " ").trim();
  if (!words) return "";
  return words[0].toUpperCase() + words.slice(1);
}
