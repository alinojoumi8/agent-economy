# W6 education integration draft

Prepared from the current source while the W5 project gates run. This is a
design draft, not an implemented or accepted education feature. W5 admission
and native acceptance remain open. Preserve the existing W5 acceptance order;
allocate new schema and semantics versions only when implementation begins.

The parent contracts are W6 in `docs/plans/2026-09-06-research-city-roadmap.md`
and S6 in `docs/plans/2026-09-06-research-city-specs.md`.

## Existing authority to reuse

| Current source | Observed behavior | Education integration |
|---|---|---|
| `engine/households.py:Households.birth` | A child receives a stable agent/person identity, household membership, guardianship and a zero-endowment checking account. | Enroll that same person. Do not create a separate school identity or replace it at adulthood. |
| `engine/cognition.py:CognitionEconomy._study_skill` | Career-review study pays the system education account and awards 10 XP. | Retain this explicitly named benchmark for historical rules. Institutional study must have a funded provider and delivered attendance. |
| `engine/cognition.py:CognitionEconomy.award_xp` | Skills and their history are authoritative; the method does not itself deduplicate awards. | Use the existing skill ledger inside an idempotent attendance settlement; do not add an independently mutable school XP balance. |
| `engine/daily_time.py:DailyTime.prepare_day` | Time-day rows already include living local children; preparation assigns civic work, care and productive work. | Reuse those rows, and specify where learner reservations and teacher delivery enter the daily order. |
| `engine/daily_time.py:DailyTime.perform` | Activities require a living adult and couple time and effects in a savepoint. | Add a narrowly authorized attendance path for enrolled children; do not weaken the general adult-action boundary. |
| `engine/labor.py:Labor.hire` | Hiring checks work eligibility and job/application status. | Add explicit versioned job skill/credential requirements; education does not guarantee a job or wage. |

Graph discovery located these scopes. Current AST reads were used where graph
source offsets were stale. Revalidate signatures and callers before editing.

## Delivery slices

1. Institution, curriculum, enrollment and funding contracts, with ordinary
   success/refusal, retry and rollback cases. No automatic XP from enrollment.
2. Scheduled attendance, teacher capacity, tuition settlement and school closure,
   sharing the existing daily-time, ledger and earned-wage authorities.
3. Completion/credentials, explicit job requirements, lifecycle and migration
   integration, historical projections and recorded replay/export.
4. A bounded education-access experiment and linked city inspectors. Measure
   household expenditure, work displacement and skill/job outcomes together;
   preserve equal goods and equity research coverage in the parent program.

Each slice stays opt-in and preserves historical stored rules. The complete W6
acceptance contract still includes all four slices.

## Data contracts

| Record | Required terms and constraints |
|---|---|
| School | Canonical operator organization, place, operating status and capacity. Private/public funding must name actual payer accounts. School teaching cannot also create ordinary manufactured output from the same work minutes. |
| Curriculum version | Skill key, rational XP rate per delivered minute, session minutes, required delivered minutes, assessment rule, teacher requirements and maximum learners per teacher. Freeze terms for an accepted enrollment. |
| Program/session | School, curriculum version, calendar, room/seat limit, tuition denomination and fee terms. A displayed place supplies no capacity unless backed by this record. |
| Application/enrollment | Existing student identity, decision tick, accepted/refused reason, effective tick, curriculum version, payer agreement, progress and end reason. One active enrollment per exclusive session slot. |
| Funding agreement | Authorized payer, student/program, currency, amount limit, expiry, refund owner and funding source. Treasury or employer support requires existing spending authority; guardianship alone cannot spend another adult's account. |
| Attendance settlement | Student, session, delivered minutes, time-allocation reference, teaching-capacity reference, fee transfer/refund references, XP history reference, fractional XP carry and unique occurrence key. |
| Assessment/credential | Student, curriculum version, criteria, evidence references, award tick and any explicit expiry/revocation. Credentials and skill levels remain distinct. |
| Job requirement | Job or occupation contract version, required skill/level and any named credential. Store point-in-time eligibility and refusal reasons without promising hiring. |

Use integer minutes, integer money and rational XP arithmetic. Curriculum terms
are model parameters, not empirical claims about real education. Start with a
small documented set; do not invent unmeasured learner intelligence or guaranteed
wage premia. An XP remainder avoids changing progress merely by splitting the
same delivered minutes into several receipts.

## Admission and funding

An adult may request their own enrollment. A child's request requires a current
authorized guardian and an explicit funding agreement. Admissions check the
student's life stage/residence, prerequisites, school status, session conflict,
capacity and payer authority before committing money or reservations. A later
guardian change does not silently transfer an existing payer's obligation.

Record every application and refusal, including capacity and funding refusals.
Declare deterministic queue/lottery ordering and a mechanism-specific random
stream when a lottery is used. Do not treat rejected applicants as missing data.

Prepaid tuition uses a dedicated ledger escrow with a named refund owner and
currency. Release only the earned amount under the frozen fee rule after actual
attendance/service delivery; refund unused amounts on the defined cancellation
or closure boundary. A missing payer, insufficient funds or currency mismatch
cannot be repaired by a hidden subsidy. Institution cash and escrow cash must
reconcile independently.

## Daily order and finite time

Specify a versioned order at the ordinary daily boundary. Resolve life stage,
residence and active enrollment before attendance. Make school attendance a
reservation in the same time-day ledger used by work, study, civic obligations,
care and travel. Adult plans must explicitly expose study time so preparation
cannot spend it on work and then charge it again for school.

Teacher availability comes from eligible active employment and actual delivered
work time after competing obligations. A class may teach several learners at
once only under the declared maximum learners per teacher. A teacher minute is
not unlimited capacity. Pay teachers through the existing earned-wage contract
once; prevent the same work allocation from producing a second kind of output.

Learner reservations do not award XP or count as delivered education. Settlement
must atomically record actual attendance, consume supported capacity, settle the
earned fee and award XP. Staff shortage or a missed session records an explicit
outcome under the declared rescheduling/refund terms. A retry returns the prior
receipt; altered terms with the same occurrence key are refused.

Reserve travel time only under an implemented travel mechanism. The existing
coarse journey charge, if used, must remain labeled as such. A rendered school
route cannot itself change costs or productive time.

## Lifecycle and population boundaries

- Birth and school entry keep the original identity; no account or skill reset.
- Adulthood preserves enrollment, skills, progress, time use and funding terms.
  Guardian authority ends under the household contract; new adult commitments
  require the adult's authority.
- Departure ends or suspends local attendance under the declared program rule.
  It creates no outside education, XP, fee income or teaching capacity. Return
  does not automatically reclaim a released seat or staff position.
- Death, incapacity, dropout and school closure settle outstanding fees and
  refunds to their recorded owners; use existing estate representation where
  applicable. A guardian's death does not erase a child's independent identity.
- A teacher's departure/death changes capacity and staffing under the existing
  employment rules. It cannot be represented only as a map animation.

## Exact examples before a campaign

1. A funded class has two seats, one teacher with 60 delivered minutes and a
   two-learners-per-teacher limit. Two students can receive 60 minutes each; a
   third application is refused or queued. Replaying settlement produces the
   same time, fees and XP, with no second teacher wage or generic goods output.
2. Reduce teacher delivery below the declared whole-session requirement. Record
   the cancelled/partial outcome chosen by that program's contract; do not award
   the full lesson or collect an unearned fee. Test both staff and learner time.
3. An adult's work, care, study and travel sum to the available daily minutes.
   One extra minute is refused without changing funds, attendance, XP or wages.
4. A child attends before turning 18, then completes after the birthday.
   The same identity and accumulated XP survive; guardian-only actions no longer
   create new adult obligations. Restart on both sides of the transition.
5. A prepaid student departs, their payer dies, and the school later closes.
   Resolve each obligation and refund once through the recorded authority and
   estate contracts; do not reinstate enrollment on return.
6. Two qualified people compete for one job. The credential affects eligibility,
   while the unfilled/filled job contract and employer decision still determine
   hiring and the agreed wage.

## Evidence and city interaction

The school inspector shows seats, applicants, enrolled students, supported
teaching time, delivered attendance, fee terms, payer coverage and closure state
at the selected run/tick. Person inspection links the same enrollment, skill and
credential evidence. Public views aggregate child/household information under
existing authorization rules. Historical selection must not request future state.

The access experiment varies one funded capacity or tuition term against a
paired control. Preserve baseline characteristics for all applicants, including
refusals. Report attendance, completion, XP, credentials, work displacement,
household costs, employer vacancies and realized wages with units and coverage.
Where firm outcomes connect to securities, report operating effects and equity
trades separately; a quote or absence of trades is not a discovered price.

Acceptance includes oversubscription, unpaid tuition, staff shortage, absence,
dropout/refund, closure, mature-age retraining, life-stage/migration collisions,
time conflicts, job eligibility and empty/non-trading outcomes. Add interrupted
phase resume, exact recorded replay and independent export readback to the
small fixtures. Freeze resource/sample/horizon terms before any later campaign;
do not reuse or reset the terminal W5 native trial's allowance.
