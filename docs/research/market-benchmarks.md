# Induced-value goods and equity benchmarks

This offline suite isolates pricing and allocation from the daily economy.
It endows small markets, executes three declared policies through the existing
goods/exchange engines, and settles cash through the ledger. It establishes
mechanical correctness and model-conditional policy behavior. It does not
validate real-world price formation or substitute for a recorded World replay.

## Contracts

| Case | Buyer values (USD cents/unit) | Seller opportunity costs | Surplus bound | Competitive price interval |
|---|---|---|---:|---|
| G1 goods | 120, 100, 80, 60 | 20, 40, 90, 130 | 160 cents | 80–90 cents/unit |
| F1 equities | 120, 110, 90, 80 | 80, 90, 110, 120 | 60 cents | 90–110 cents/share |

Each buyer demands at most one unit and starts with cash equal to its value.
Each seller starts with one unit. Goods are homogeneous endowed inventory;
the stated seller cost is an opportunity cost, not an incurred production bill.
There is no borrowing, resale, shorting, fee or production in these fixtures.

F1 has four shares, each redeemable for 100 cents after the last auction. A
separate account receives 400 cents from the explicit external endowment at
genesis. Redemption pays every terminal holder, including non-trading sellers,
then extinguishes all four shares. Private reservation values include utility
or liquidity preferences, so measured surplus is distinct from cash profit.
This isolated fixture does not add dividends/redemption to ordinary firms.

The surplus oracle sorts buyer values downward and seller costs upward, then
sums positive matched differences. Its result is independently checked against
exhaustive feasible allocations in small randomized tests. The competitive
interval uses marginal participating and excluded values/costs. Zero-surplus
marginal trades are excluded from the selected efficient quantity; other
zero-surplus allocations can also be optimal.

## Policies and information

| Policy | Buyer rule | Seller rule |
|---|---|---|
| `value_bound_v1` | Bid own reservation value | Ask own opportunity cost |
| `seeded_noise_v1` | Hash-keyed bid from 1 through own value | Own cost plus a hash-keyed margin from 0 through 100 |
| `adaptive_margin_v1` | Start 30 cents below own value; increase 10 after an unfilled session, bounded by own value | Start 30 above cost; reduce 10 after an unfilled session, bounded by own cost |

Policies receive their own reservation, remaining unit and unsuccessful-session
count. Goods buyers see current posted asks and shop the cheapest acceptable
remaining offer. Equity orders clear by production price-time priority after
the session's submissions and expire at session close. No policy reads other
actors' reservation values. Reports contain the researcher-visible values.

Arrival and noisy quotes use independent SHA-256 keys containing case, seed,
session, actor and purpose. Extra activity by one actor cannot consume another's
draw. This contract applies only to these fixtures; it does not change the
daily world's legacy shared randomness. `value_order` is an optional controlled
arrival fixture, not a hidden-information policy: it is useful for known answers.

## Run and inspect

```powershell
.\.venv\Scripts\python.exe -m research.benchmarks --seeds 1 2 3 --sessions 4 --validate-only
.\.venv\Scripts\python.exe -m research.benchmarks --seeds 1 2 3 --sessions 4
```

The suite always assigns both cases and all three policies. Protocol limits
are 20 unique seeds, five sessions, and 32 buyers/sellers per fixture (the
current cases each have four). The campaign wall-time guard is checked between
bounded assignments; it is not a process timeout. No provider is called.

Every launch claims a unique namespace and freezes the protocol, exact case
values, metric definitions, policy versions and code identity. Each cell keeps
its claim, source database, fresh rerun database, canonical comparison and
result receipt. Failed/partial files remain; later unstarted assignments remain
in cohort counts. Code changes during execution exclude the campaign.

`verify_benchmark` checks bound file hashes, pending WAL changes, assignment
identity, source measurements, reconciliation and a fresh canonical-table
comparison. This is labeled `deterministic_mechanics_rerun`; it must never be
presented as recorded LLM/World replay. Final eligibility also retains campaign
guards, and a loader must not promote an excluded row based only on its database
comparison. The interactive study loader/export remains a separate delivery.

## Interpret findings

Reports retain allocation surplus, efficiency, quantities, VWAP, distance from
the competitive interval, equity redemption-price error, non-trading and unfilled
buyers. Missing execution prices remain null. Efficiency is undefined when
feasible surplus is zero. The declared price protocols need not clear at a
competitive price, even when allocation reaches the surplus bound.

Paired policy differences use one market assignment/seed as the unit, matching
complete canonical genesis state. Bootstrap intervals resample whole pairs;
fewer than the declared minimum gives descriptive observations without an
interval. These small fixed-value markets are exploratory, not confirmatory
evidence about adaptive agents generally. In particular, non-trading under a
noise policy is an economic outcome that remains eligible.
