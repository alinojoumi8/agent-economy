# Task 8 report: inspect institutional and operations evidence

## Summary

- Added native inspection buttons for legal matters, legal obligations, bills, startup summaries and records, acceptance checks, shock traces, and provider costs.
- Preserved the surrounding `article`, `dl`, `div`, and existing table semantics; every new inspection button contains phrasing content only.
- Kept Oracle submission and suggestions, calibration state, acceptance progress, and all non-inspection behavior unchanged.
- Added the shared inspector, focus-bar, inspectable-card, mobile drawer, and reduced-motion styles.
- Regenerated and included the production dashboard static bundle hash replacement.

## Files

- `dashboard/src/components/V2Observatory.jsx`
- `dashboard/src/components/AcceptancePanel.jsx`
- `dashboard/src/components/OracleAndCost.jsx`
- `dashboard/src/index.css`
- `dashboard/tests/observatory-interaction.test.js`
- `server/static/index.html`
- `server/static/assets/MacroOverview-CsA3QXFT.js`
- `server/static/assets/index-BQwC2Phe.js`
- `server/static/assets/index-Bzknuz9v.css`
- Replaced prior hashed files: `MacroOverview-ceoIoWVf.js`, `index-BcQvRSMs.js`, and `index-6abtIarH.css`

## Tests

### RED

Command:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Observed before implementation: 17 tests, 15 passed and 2 failed. The mounted extended-panel test could not find `Inspect legal matter Docket Alpha`, and the semantic/style test found no native inspection button. Both were the expected missing-feature failures.

### GREEN

Command:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Observed after implementation: 17 passed, 0 failed.

Command:

```bash
cd dashboard && npm test && npm run build
```

Observed: full dashboard suite 49 passed, 0 failed. Vite 8.1.4 transformed 607 modules and built successfully, emitting `index-BQwC2Phe.js`, `index-Bzknuz9v.css`, and `MacroOverview-CsA3QXFT.js`.

## Contract coverage

- The mounted `react-test-renderer` harness invokes every extended inspection button rendered by representative fixtures and asserts exact kinds, IDs, collections, references, and snapshots, including the shared-agent fallback ID.
- SSR checks retain semantic wrappers, reject role-button wrappers and `tabindex="0"`, and reject block content inside every native button.
- CSS checks cover the focus bar, drawer, inspectable cards, mobile drawer layout, and reduced-motion behavior.

## Concerns

None.
