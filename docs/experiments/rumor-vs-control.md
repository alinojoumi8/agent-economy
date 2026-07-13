# Rumor vs. control — five-seed experiment

**Evidence date:** 2026-07-13

**Specification:** [`runs/experiments/rumor_vs_control.yaml`](../../runs/experiments/rumor_vs_control.yaml)

**Provider mode:** deterministic scripted/offline

**Design:** 5 seeds × 2 matched arms × 30 ticks = 10 complete worlds

## Question

Does a false solvency rumor about Bank 1 cause deposit flight beyond the matched
same-seed baseline?

Each treatment world receives the rumor at tick 10. Its control twin uses the
same seed and configuration without the shock. Every arm runs the complete world
loop and must pass ledger reconciliation before entering the distribution.

## Reproduction

```powershell
python run.py --experiment runs/experiments/rumor_vs_control.yaml
```

The command writes derived databases to `data/experiments/rumor_vs_control/` and
the full generated comparison to `reports/out/experiment_rumor_vs_control.html`.
Both locations are intentionally ignored because the experiment is reproducible
from the committed specification.

## Results

All 10 arms reached tick 30 and reconciled. Total provider spend was $0 because
this is the offline acceptance profile.

| Outcome at tick 30 | Treatment mean ± population SD | Control mean | Mean effect (T−C) |
|---|---:|---:|---:|
| Bank 1 deposits (cents) | 394,424.854 ± 95,231.652 | 1,200,534.760 | **−806,109.906** |
| Bank 1 reserve ratio | 0.1010 ± 0.0019 | 0.5891 | **−0.4881** |
| Sentiment | −0.7619 ± 0.0226 | 0.0117 | **−0.7736** |
| Market index | 100.0000 ± 0.0000 | 100.0000 | 0.0000 |
| Unemployment | 0.0077 ± 0.0154 | 0.0077 | 0.0000 |

| Event count per run | Treatment mean | Control mean | Mean effect (T−C) |
|---|---:|---:|---:|
| Deposit moves | **16.8** | **0.0** | **+16.8** |
| Bank failures | 0.0 | 0.0 | 0.0 |
| Lender-of-last-resort grants | 0.0 | 0.0 | 0.0 |

## Interpretation

The treatment-control separation is large and directionally consistent with the
specified mechanism: informational exposure changes trust, agents choose to move
deposits, and reserve settlement weakens the target bank. The experiment does
not claim a bank failure; the observed outcome is a run that drives the bank to
its 10% reserve floor without failure or central-bank support in these seeds.

This satisfies the PRD's written N=5 experiment artifact for the functional
prototype under semantics v3. It does **not** prove that MiniMax/Kimi agents reproduce the same
distribution. That production confirmation requires provider keys, approved
spend, and a separately retained real-provider run.
