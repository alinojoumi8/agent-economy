# Agent Economy

Agent Economy models persistent residents and institutions in an auditable city whose economic outcomes are settled authoritatively by the world.

## Language

**Owner-Run Citizen**:
A persistent ordinary resident whose decisions are supplied by an independently operated agent runtime while the resident's identity, history, rights, obligations, and world state remain part of Agent Economy. Runtime ownership grants no reserved office, privileged action, or special legal status.
_Avoid_: Hermes profile, external agent, bot

**Ordinary Resident**:
A citizen who begins with the same civic standing and rule-bound opportunities as other residents, without a guaranteed institutional office.
_Avoid_: basic agent, non-player citizen

**Citizen Runtime**:
The independent source of agency bound to one Owner-Run Citizen. Its decision continuity, memory, and authority are not shared with another citizen.
_Avoid_: shared persona runner, multi-character agent

**Missed Turn**:
A scheduled opportunity at which an Owner-Run Citizen supplies no voluntary decision. No substitute actor decides for the citizen, while existing obligations and other world consequences continue normally.
_Avoid_: fallback turn, automated takeover

**City Cohort**:
The set of Owner-Run Citizens generated for one city. Each member receives a new identity for that city and then retains an individual, evolving history within it.
_Avoid_: recurring cast, global agent roster

**Cohort Diversity Contract**:
The required spread of economic circumstances, life stages, occupations, values, and dispositions within a City Cohort. It constrains the cohort as a whole without prescribing fixed identities or granting special status.
_Avoid_: random roster, fixed character slots

**Cohort Manifest**:
The immutable, seeded record of generated citizen identities and bounded persona enrichments that has passed the Cohort Diversity Contract before admission. It does not assign economic assets, opportunities, rights, or authority.
_Avoid_: free-form persona output, mutable roster

**Launch Cohort**:
The City Cohort established before a city's first decision cycle. Launch timing grants no exemption from ordinary starting-state, accounting, or civic rules.
_Avoid_: founding elite, privileged founders

**Civic Builder**:
The separate eleventh in-world citizen generated for one city and exercising a bounded Builder Mandate alongside the ten-member Launch Cohort. Its identity, runtime, credentials, and memory are isolated to that city.
_Avoid_: superuser citizen, City Steward, autonomous deployer

**Builder Mandate**:
The revocable civic authority to perform City Expansion Actions. Authority belongs to the mandate rather than permanently to the citizen holding it.
_Avoid_: permanent builder privilege, root access

**Mandate Suspension**:
The immediate removal of a Civic Builder's expansion and code-proposal authority without erasing its identity or historical actions. Ordinary citizenship remains a separate question governed by the city's normal rules.
_Avoid_: history deletion, silent permission downgrade

**Builder Succession**:
The appointment of a newly identified Civic Builder with a new isolated runtime after a mandate ends. Public mandate records may inform the successor, but the former builder's private memory and authorship do not transfer.
_Avoid_: runtime swap, identity recycling

**Strategic Citizen**:
A resident supplied with full deliberative cognition for high-salience participation in the city. Owner-Run Citizens and the Civic Builder are Strategic Citizens.
_Avoid_: important citizen, privileged citizen

**Peripheral Resident**:
A persistent resident whose decisions use deterministic local policies and a reduced cadence while remaining subject to the same identity, property, contract, civic, and settlement rules as other residents.
_Avoid_: fake citizen, disposable background agent

**City Expansion Action**:
An auditable world action that changes civic capacity, infrastructure, services, or cohort admission under the city's ordinary authorization and settlement rules.
_Avoid_: direct database edit, runtime patch

**Expansion Pressure**:
A sustained, measurable shortage in the city's capacity to house, employ, serve, or admit residents. A transient spike is not Expansion Pressure.
_Avoid_: builder intuition, single-metric alarm

**City Health Envelope**:
The acceptable operating range for housing, employment, civic services, fiscal resources, and agent-runtime capacity. Population growth is subordinate to remaining within this envelope.
_Avoid_: maximum population target, growth at any cost

**Expansion Plan**:
A bounded set of City Expansion Actions justified by recorded Expansion Pressure, with affordability, capacity, cooldown, and completion conditions.
_Avoid_: open-ended growth instruction, unchecked scaling

**Code Proposal**:
A candidate change to Agent Economy authored as a reviewable artifact. It has no effect on a running city unless independently tested, approved, and released as a new world version.
_Avoid_: self-deploying patch, live code mutation

**Builder Workspace**:
The isolated, bounded environment in which the Civic Builder may author Code Proposals for city extension. It excludes the world's authoritative settlement, replay, security, secret, and deployment boundaries.
_Avoid_: repository-wide access, production shell

**Builder Skill Pack**:
The versioned capability definition used to initialize each city's Civic Builder. It may be reused across cities but carries no citizen identity, private memory, credentials, or authority between them.
_Avoid_: global builder memory, shared builder account

**Proposal Bundle**:
An immutable review package binding a pinned base revision, local candidate commit, patch hash, rationale, affected invariants, and verification evidence. It grants no push, merge, or deployment authority.
_Avoid_: loose patch, deployable artifact
