# Local reproducibility release profile

`reproducibility-v1` is the local-only evidence profile for mechanics,
determinism, documentation, and build reproducibility. It is not a public
release, hosted-readiness, live-provider, or independent-connector gate.

The offline collector uses the manifest's explicit `profile` to choose one
fixed gate inventory. An omitted profile defaults to the strict
`production-v1` inventory for backward compatibility. An unknown profile fails closed
and is never allowed to select a smaller custom gate set.

## Fixed local gates

| Gate | Evidence boundary |
|---|---|
| `python_core_regression` | Maintained Python mechanics and invariant tests |
| `recorded_replay` | Exact recorded-source replay checks |
| `scale_profile_contract` | Maintained scale-profile contracts |
| `dashboard_regression` | Dashboard unit tests |
| `dashboard_typecheck` | TypeScript typecheck |
| `dashboard_build` | Fresh production build and committed-bundle review |
| `pinned_dataset_verification` | Offline verification of pinned datasets |
| `documentation_contract` | Maintained documentation and local-link tests |
| `local_secret_scan` | The repository's approved, pinned local secret scan |

Every referenced receipt must use `execution_scope: local`, bind the exact
clean candidate commit and tree, pass its gate, identify a bounded environment,
and hash every referenced artifact. A live-provider or
`independent_external` receipt is ineligible for this profile even if its own
status says `passed`.

Use the maintained command owner below when producing each receipt. Record the
literal command in the receipt and retain a sanitized, repository-relative log
as its hashed artifact.

| Gate | Maintained command owner |
|---|---|
| `python_core_regression` | The `core-subset` job in [CI](../.github/workflows/ci.yml), including its exact file list and single-shard flags |
| `recorded_replay` | `python -m pytest -q tests/test_recorded_replay_golden.py tests/test_replay_source_lifecycle.py` |
| `scale_profile_contract` | `python -m pytest -q tests/test_scale_170_profiles.py tests/test_scale_270_profiles.py tests/test_scale_validation.py tests/test_scale_economic_health.py` |
| `dashboard_regression` | `npm --prefix dashboard test` |
| `dashboard_typecheck` | `npm --prefix dashboard run typecheck` |
| `dashboard_build` | `npm --prefix dashboard run build`, followed by the committed-bundle drift checks in [development](development.md) |
| `pinned_dataset_verification` | `python run.py --verify-datasets config/data-manifest.yaml` |
| `documentation_contract` | `python -m pytest -q tests/test_documentation.py` |
| `local_secret_scan` | Gitleaks `8.30.1` with `.gitleaks.toml` against the candidate Git history/tree, with `--redact` enabled |

Do not substitute a smaller ad hoc test list, an unpinned secret scanner, a
staged-only scan of an empty index, or a previously generated dashboard bundle.
If a maintained command changes, the configuration hash and receipt must change.

## Assemble an offline package

Copy the template rather than editing the template in place:

```powershell
Copy-Item runs/release/reproducibility-v1.template.yaml `
  runs/release/reproducibility-v1.yaml
```

Fill the exact candidate commit/tree plus repository-relative receipt paths and
SHA-256 values. The collector validates existing bytes; it does not run tests,
contact providers, deploy infrastructure, or generate missing evidence.

Write receipts, logs, the filled manifest, and the selected package below
`reports/out/`, which is intentionally ignored. That keeps evidence bound to the
clean candidate named in the manifest instead of changing that candidate by
committing its own run output. Preserve or publish the package separately only
under an explicit evidence-retention decision.

```powershell
python run.py `
  --release-evidence-report runs/release/reproducibility-v1.yaml `
  --output reports/out/reproducibility-v1
```

The command writes authoritative canonical JSON and a deterministic Markdown
review. It exits nonzero when a gate is missing, blocked, failed, not run,
mis-scoped, mismatched to the candidate, unhashed, unsafe, or secret-bearing.
On Windows, use a new output directory for a changed selected package; the
collector deliberately refuses to replace an already-selected directory
symlink in place.

## Boundary with production evidence

The strict template remains
[`runs/release/manifest-v1.template.yaml`](../runs/release/manifest-v1.template.yaml)
and now names `profile: production-v1` explicitly. It retains all 16 gates,
including independent connectors, live campaigns, hosted operations, tenant
isolation, backup/restore, acceptance, provenance, and deployment evidence.

Passing `reproducibility-v1` cannot satisfy or waive any production gate. It
cannot support a public-readiness claim, and it does not change the release
state recorded in [implementation status](implementation-status.md). Keep the
generated package as candidate-bound evidence, not as maintained narrative
documentation.
