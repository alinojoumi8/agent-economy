# Investigation Workspace Conflict and Export Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add title editing with explicit HTTP 409 conflict recovery and privacy-safe JSON/Markdown downloads to the World OS Investigation workspace.

**Architecture:** Preserve server records as authoritative while holding the analyst's title draft in an explicit pure state model. Surface HTTP status through a typed workspace error, stop on 409, fetch the current server record, and offer Reload or Save-as-new without automatic merging. Keep download creation in a dependency-injected helper so Blob URLs, filenames, and cleanup are unit-testable.

**Tech Stack:** React 19, TypeScript/JavaScript modules, TanStack Query, FastAPI, SQLite operator workspace, Node test runner, Playwright Chromium.

## Global Constraints

- Never automatically retry a stale write or silently overwrite a newer server version.
- Preserve the local title draft on 409 and on non-conflict network/server failures.
- Save-as-new copies only title and run/fork/tick/query/layout context; existing evidence and hypotheses remain on the original record.
- Export only the backend's redacted JSON/Markdown response.
- Never place investigation content or export bytes in URL state, localStorage, sessionStorage, IndexedDB, console, analytics, or error telemetry.
- Keep the operator workspace separate from the replay-authoritative run database.
- Real Chromium conflict and privacy tests are required; backend tests alone do not close the UI gap.

---

## File structure

- Modify: `dashboard/src/app/api.ts` — typed `WorkspaceApiError` with status and detail.
- Create: `dashboard/src/workspaces/investigationState.js` — pure draft/conflict state transitions.
- Create: `dashboard/src/lib/downloadText.js` — dependency-injected Blob download and URL cleanup.
- Create: `dashboard/src/components/InvestigationTitleEditor.tsx` — title input, validation, save/cancel.
- Create: `dashboard/src/components/InvestigationConflictDialog.tsx` — local/server comparison and explicit actions.
- Create: `dashboard/src/components/InvestigationExportActions.tsx` — JSON/Markdown controls and errors.
- Modify: `dashboard/src/workspaces/InvestigationsWorkspace.tsx` — query/mutation orchestration.
- Modify: `dashboard/src/index.css` — conflict/editor layout, focus, narrow viewport, reduced motion.
- Create: `dashboard/tests/investigation-workspace.test.js` — pure state/error/download/source contracts.
- Create: `dashboard/tests/e2e/world-os-investigations.spec.ts` — two-context stale-version and downloads.
- Modify: `dashboard/tests/e2e/world-os-privacy.spec.ts` — investigation export canary/storage coverage.
- Modify: `tests/test_operator_workspace.py` — preserve backend optimistic concurrency/export contract.
- Modify: `docs/test-cases.md` — mark the two contractual gaps automated only after browser evidence passes.

### Task 1: Expose typed workspace HTTP failures

**Files:**
- Modify: `dashboard/src/app/api.ts`
- Create: `dashboard/tests/investigation-workspace.test.js`

**Interfaces:**
- Produces: `WorkspaceApiError extends Error` with `status: number` and `detail: unknown`.
- Consumes: existing `workspaceApi<T>(path, options)` callers without changing success values.

- [ ] **Step 1: Add a failing source contract test**

Add a Node test that reads `dashboard/src/app/api.ts` and asserts the typed error is exported and thrown with `response.status`. Add runtime units for the factored `workspaceErrorMessage` function:

```javascript
assert.equal(workspaceErrorMessage({ detail: "investigation version conflict" }, 409),
  "investigation version conflict");
assert.equal(workspaceErrorMessage({}, 503), "Workspace request failed (503)");
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
(cd dashboard && node --test tests/investigation-workspace.test.js)
```

Expected: missing export/assertion failure.

- [ ] **Step 3: Implement the typed error without changing success behavior**

Add:

```typescript
export class WorkspaceApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "WorkspaceApiError";
    this.status = status;
    this.detail = detail;
  }
}
```

`workspaceApi` must parse the response once, derive a safe string message, and throw `WorkspaceApiError(response.status, payload.detail, message)`. Do not serialize the full response or request headers into the error.

- [ ] **Step 4: Run unit and type checks**

Run:

```bash
(
  cd dashboard
  node --test tests/investigation-workspace.test.js
  npm run typecheck
)
```

Expected: pass and existing callers typecheck.

- [ ] **Step 5: Commit the API boundary**

Run:

```bash
git add dashboard/src/app/api.ts dashboard/tests/investigation-workspace.test.js
git diff --cached --check
git commit -m "feat(dashboard): expose workspace HTTP conflicts"
```

### Task 2: Implement pure title-draft and conflict state

**Files:**
- Create: `dashboard/src/workspaces/investigationState.js`
- Modify: `dashboard/tests/investigation-workspace.test.js`

**Interfaces:**
- Produces: `createInvestigationDraft(record)`, `editInvestigationTitle(state, title)`, `acceptSavedInvestigation(state, record)`, `openInvestigationConflict(state, record)`, and `reloadInvestigationConflict(state)`.
- Consumes: records with `{id,title,version,run_id,fork_id,pinned_tick,query,layout}`.

- [ ] **Step 1: Write failing transition tests**

Add:

```javascript
const serverV1 = { id: "inv-1", title: "Original", version: 1, run_id: "run-demo" };
let state = createInvestigationDraft(serverV1);
state = editInvestigationTitle(state, "Local draft");
assert.equal(state.dirty, true);

state = openInvestigationConflict(state, { ...serverV1, title: "Remote title", version: 2 });
assert.equal(state.titleDraft, "Local draft");
assert.equal(state.conflict.server.title, "Remote title");
assert.equal(state.conflict.submittedVersion, 1);

state = reloadInvestigationConflict(state);
assert.equal(state.titleDraft, "Remote title");
assert.equal(state.dirty, false);
assert.equal(state.conflict, null);
```

Also test successful save, cancel, whitespace/160-character validation, and switching records.

- [ ] **Step 2: Run tests and verify missing exports**

Run:

```bash
(cd dashboard && node --test tests/investigation-workspace.test.js)
```

- [ ] **Step 3: Implement immutable transitions**

State shape:

```javascript
{
  server: record,
  titleDraft: record.title,
  dirty: false,
  conflict: null,
  error: "",
}
```

Transitions must return new objects, preserve local draft on conflict/error, and never change the server version during `editInvestigationTitle`.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
(cd dashboard && node --test tests/investigation-workspace.test.js)
git add src/workspaces/investigationState.js tests/investigation-workspace.test.js
git diff --cached --check
git commit -m "feat(dashboard): model investigation edit conflicts"
```

### Task 3: Add title editing and successful optimistic save

**Files:**
- Create: `dashboard/src/components/InvestigationTitleEditor.tsx`
- Modify: `dashboard/src/workspaces/InvestigationsWorkspace.tsx`
- Modify: `dashboard/src/index.css`
- Modify: `dashboard/tests/investigation-workspace.test.js`

**Interfaces:**
- Consumes: Task 2 draft state and Task 1 `WorkspaceApiError`.
- Produces: PATCH body `{expected_version,title}` and accessible editor callbacks.

- [ ] **Step 1: Add a failing rendered-source contract**

Assert source contains a labelled title input, 160-character limit, Save and Cancel buttons, and sends `expected_version: draft.server.version`. Add a pure payload test:

```javascript
assert.deepEqual(investigationUpdatePayload(state), {
  expected_version: 1,
  title: "Local draft",
});
```

- [ ] **Step 2: Run unit tests and verify failure**

Run:

```bash
(cd dashboard && npm test)
```

- [ ] **Step 3: Implement the editor component**

Props:

```typescript
type InvestigationTitleEditorProps = {
  title: string;
  serverTitle: string;
  version: number;
  pending: boolean;
  error: string;
  onChange(title: string): void;
  onSave(): void;
  onCancel(): void;
};
```

Disable Save when unchanged, blank after trimming, longer than 160 characters, or pending. Cancel restores the fetched server title.

- [ ] **Step 4: Wire PATCH success in the workspace**

On success, replace the cached record, accept the returned version, invalidate the investigation list, and clear dirty/error/conflict state. Do not navigate away.

- [ ] **Step 5: Protect dirty navigation**

When the route changes to another investigation while dirty, show a focused confirmation that offers Stay or Discard draft and continue. Do not use `beforeunload` as the only protection.

- [ ] **Step 6: Run unit/type/build checks and commit**

Run:

```bash
(
  cd dashboard
  npm test
  npm run typecheck
  npm run build
  git add src/components/InvestigationTitleEditor.tsx src/workspaces/InvestigationsWorkspace.tsx src/index.css tests/investigation-workspace.test.js
  git diff --cached --check
  git commit -m "feat(dashboard): edit investigation titles"
)
```

### Task 4: Add explicit 409 recovery and Save-as-new

**Files:**
- Create: `dashboard/src/components/InvestigationConflictDialog.tsx`
- Modify: `dashboard/src/workspaces/InvestigationsWorkspace.tsx`
- Modify: `dashboard/src/index.css`
- Modify: `dashboard/tests/investigation-workspace.test.js`
- Modify: `tests/test_operator_workspace.py`

**Interfaces:**
- Consumes: `WorkspaceApiError.status === 409`, current detail GET, Task 2 conflict state.
- Produces: Reload, Continue editing, and Save draft as new actions.

- [ ] **Step 1: Strengthen backend conflict tests**

In `tests/test_operator_workspace.py`, assert stale update leaves title/version/audit count unchanged and current detail returns the winning title/version. Also assert create-as-new preserves owner/run/fork/tick/query/layout while receiving a new ID and version 1.

- [ ] **Step 2: Add failing frontend conflict tests**

Assert the dialog displays:

```text
Your draft: Local draft
Server version 2: Remote title
Reload server version
Save draft as new investigation
Continue editing
```

Assert no automatic second PATCH occurs.

- [ ] **Step 3: Run focused tests and observe failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_workspace.py -q
(cd dashboard && npm test)
```

- [ ] **Step 4: Implement 409 orchestration**

Catch only `WorkspaceApiError` with status 409, GET the current detail, and open conflict state. Non-409 errors set safe inline error text while retaining the draft. Never log the draft.

- [ ] **Step 5: Implement explicit actions**

Reload adopts the fetched server record. Continue editing closes the dialog but keeps the local draft and stale submitted version; Save stays unavailable until the analyst reloads or saves as new. Save-as-new POSTs:

```typescript
{
  title: draft.titleDraft.trim(),
  fork_id: conflict.server.fork_id,
  pinned_tick: conflict.server.pinned_tick,
  query: conflict.server.query,
  layout: conflict.server.layout,
}
```

On success, navigate to the new investigation. State clearly that evidence/hypotheses remain on the original.

- [ ] **Step 6: Implement focus behavior**

Focus the conflict heading on open, trap focus while open, close on Escape only when no mutation is pending, and return focus to the title input.

- [ ] **Step 7: Run and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_workspace.py -q
(cd dashboard && npm test && npm run typecheck && npm run build)
git add src/components/InvestigationConflictDialog.tsx src/workspaces/InvestigationsWorkspace.tsx src/index.css tests/investigation-workspace.test.js ../tests/test_operator_workspace.py
git diff --cached --check
git commit -m "feat(dashboard): resolve investigation version conflicts"
```

### Task 5: Implement privacy-safe JSON and Markdown downloads

**Files:**
- Create: `dashboard/src/lib/downloadText.js`
- Create: `dashboard/src/components/InvestigationExportActions.tsx`
- Modify: `dashboard/src/workspaces/InvestigationsWorkspace.tsx`
- Modify: `dashboard/tests/investigation-workspace.test.js`
- Modify: `tests/test_operator_workspace.py`

**Interfaces:**
- Produces: `downloadText({documentRef,urlApi,BlobCtor,filename,mimeType,text})` and export actions.
- Consumes: GET `/api/v2/operator/investigations/{id}/export` response `{json,markdown}`.

- [ ] **Step 1: Add backend redaction tests**

Assert JSON format `world-os-investigation-v1`, redaction manifest values, owner isolation, no operator audit, and no private message body. Assert Markdown includes title/run/hypotheses/evidence stable references but no private fields.

- [ ] **Step 2: Add failing download-helper tests**

Use fakes to assert:

```javascript
assert.deepEqual(blobParts, [expectedText]);
assert.equal(anchor.download, "inv-1.json");
assert.equal(anchor.clicks, 1);
assert.deepEqual(revokedUrls, ["blob:test"]);
```

Also assert anchor removal and URL revocation occur when click throws.

- [ ] **Step 3: Implement the helper with `finally` cleanup**

Create the Blob, object URL, hidden anchor, click once, then remove the anchor and revoke the URL in `finally`. Reject filenames not matching `^[A-Za-z0-9._-]+\.(json|md)$`.

- [ ] **Step 4: Implement export controls**

Fetch once per click, serialize JSON as `JSON.stringify(payload.json, null, 2) + "\n"`, and name the download with the investigation ID followed by `.json` or `.md`. Use `application/json` for JSON and `text/markdown;charset=utf-8` for Markdown. Pending state prevents duplicate requests. Failure produces inline copy and no Blob.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_workspace.py -q
(cd dashboard && npm test && npm run typecheck && npm run build)
git add src/lib/downloadText.js src/components/InvestigationExportActions.tsx src/workspaces/InvestigationsWorkspace.tsx tests/investigation-workspace.test.js ../tests/test_operator_workspace.py
git diff --cached --check
git commit -m "feat(dashboard): export investigation evidence"
```

### Task 6: Prove two-context conflicts, downloads, privacy, and accessibility in Chromium

**Files:**
- Create: `dashboard/tests/e2e/world-os-investigations.spec.ts`
- Modify: `dashboard/tests/e2e/world-os-privacy.spec.ts`
- Modify: `docs/test-cases.md`

**Interfaces:**
- Consumes: complete UI/backend workflow.
- Produces: real Chromium receipts for both former contractual gaps.

- [ ] **Step 1: Build a stateful Playwright investigation mock**

The mock must maintain title/version in test scope, validate CSRF, increment version on accepted PATCH, return 409 on stale PATCH, return current detail, create new IDs, and serve redacted export bytes. Do not short-circuit the UI with direct state injection.

- [ ] **Step 2: Test a real stale-version workflow with two contexts**

Context A and B load version 1. A saves `Remote title` and receives version 2. B keeps `Local draft`, submits version 1, sees both titles, and makes no automatic retry. Verify Reload. Repeat and verify Save-as-new navigates to the new ID while the original retains version 2.

- [ ] **Step 3: Test both downloads**

Use Playwright's download event. Assert suggested filenames, JSON parseability/schema/redaction manifest, Markdown title/run/evidence, and absence of the private canary.

- [ ] **Step 4: Extend the privacy scan**

Seed canaries in private bodies, sensitive external action fields, server errors, and export mock internals. After edit, conflict, save-as-new, and download, scan DOM, URL, localStorage, sessionStorage, IndexedDB names/records, console, page errors, request failures, and downloaded bytes.

- [ ] **Step 5: Test keyboard and focus behavior**

Tab to the title input, save with keyboard, trigger conflict, assert focus enters the dialog, use Reload/Save-as-new, close with Escape where allowed, and verify focus restoration. Run at desktop and narrow viewport; assert no page-level horizontal overflow.

- [ ] **Step 6: Run the focused browser suite**

Run:

```bash
(
  cd dashboard
  npm run test:e2e -- --project=chromium tests/e2e/world-os-investigations.spec.ts tests/e2e/world-os-privacy.spec.ts
)
```

Expected: all pass with zero page errors, console errors, request failures, and canary leaks.

- [ ] **Step 7: Update contractual-gap statuses only after evidence passes**

Change `AE-EXT-INVESTIGATION-CONFLICT-001` and `AE-EXT-EXPORT-BROWSER-UI-001` from `contractual-gap` to `newly-automated`, name the exact Playwright tests, and retain their `full-offline` tier.

- [ ] **Step 8: Commit browser evidence**

Run:

```bash
git add dashboard/tests/e2e/world-os-investigations.spec.ts dashboard/tests/e2e/world-os-privacy.spec.ts docs/test-cases.md
git diff --cached --check
git commit -m "test(dashboard): prove investigation conflicts and exports"
```

### Task 7: Run the complete integration gate

**Files:**
- Verify: all files from Tasks 1–6.

**Interfaces:**
- Consumes: completed feature.
- Produces: merge-ready browser/UI work with no release claim.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_workspace.py tests/test_semantics8_projections_api.py tests/test_research_export.py -q
```

Expected: pass.

- [ ] **Step 2: Run the complete dashboard gate**

Run:

```bash
(
  cd dashboard
  npm ci
  npm test
  npm run typecheck
  npm run licenses:check
  npm audit --audit-level=high
  npm run test:e2e -- --project=chromium
  npm run build
)
```

Expected: all pass and zero high-severity vulnerabilities.

- [ ] **Step 3: Run Python shards and documentation checks**

Run all eight maintained Python shards, then:

```bash
.venv/bin/python -m pytest tests/test_documentation.py -q
git diff --check main...HEAD
```

- [ ] **Step 4: Manually verify in real Google Chrome**

Create an investigation, edit title, trigger a conflict from a second tab, exercise all three conflict actions, download JSON/Markdown, inspect focus and narrow layout, and confirm no browser console/network failures.

- [ ] **Step 5: Request review and prepare the PR**

Review every finding against current control flow, add focused regressions for real defects, rerun affected gates, and open a PR only with a clean tracked tree and recorded Chromium result.
