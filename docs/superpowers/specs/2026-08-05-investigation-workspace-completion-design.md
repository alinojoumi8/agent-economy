# Investigation Workspace Conflict and Export Completion Design

## Goal

Complete the browser-facing operator investigation workflow by adding editable titles with explicit optimistic-concurrency conflict handling and privacy-safe JSON/Markdown downloads. The UI must preserve analyst work without mutating replay-authoritative truth or leaking privileged content into browser persistence.

## Existing contracts

The backend already provides:

- `PATCH /api/v2/operator/investigations/{id}` with `expected_version` and HTTP 409 on a stale version;
- `POST /api/v2/operator/investigations` for a new operator-owned record;
- `GET /api/v2/operator/investigations/{id}/export` returning redacted structured JSON and Markdown;
- owner isolation, CSRF validation, stable references, and operator-workspace persistence separate from the run database.

The current React workspace displays the title and version but exposes neither editing nor export. Existing create, pin, and hypothesis mutations invalidate the list after success but do not provide a general conflict surface.

## Considered approaches

### 1. Explicit draft state with Reload and Save-as-new conflict choices — selected

Keep the editable title in local component state, send the current server version with the patch, and stop on 409. Fetch the latest server record, show both values, and let the analyst choose Reload or Save draft as new. This matches the backend contract and avoids silently overwriting another session.

### 2. Automatic last-write-wins retry

Retrying with the new version could destroy another analyst's change and would make the version contract cosmetic.

### 3. Field-level automatic merge

Only the title is initially editable, so a merge engine adds complexity without meaningful benefit. Future multi-field editing can add explicit comparison per field.

## Editing state model

The workspace maintains:

- `serverInvestigation`: the last fetched authoritative record;
- `titleDraft`: the analyst's unsaved text;
- `dirty`: whether the draft differs from the server title;
- `conflict`: the stale submitted version, local draft, and newly fetched server record;
- mutation status and an accessible error message.

Selecting another investigation with a dirty draft requires confirmation before discarding it. Successful save replaces the server record, updates the route cache, and clears dirty/conflict state. Non-conflict errors retain the draft and expose a retry action.

## Conflict behavior

On HTTP 409, the client never automatically retries. It fetches the latest investigation detail and opens an accessible conflict panel showing local title, server title, submitted version, and current version.

- **Reload server version** replaces the draft and closes the conflict.
- **Save draft as new investigation** creates a new operator investigation with the local title and the current run/fork/tick/query/layout context. Persisted evidence and hypotheses remain on the original record; the UI states this explicitly before creation.
- **Continue editing** closes the comparison panel but preserves the dirty draft; a later save still uses the newly displayed server version only after the analyst explicitly reloads or saves as new.

The original record is never patched again from a stale draft without a new deliberate edit based on its current version.

## Export behavior

The export control offers separate JSON and Markdown downloads. One authorized request may retrieve both representations. The client serializes the JSON representation with stable indentation and writes each payload to a short-lived `Blob` URL. It triggers filenames `<investigation-id>.json` and `<investigation-id>.md`, then revokes the URL.

Export bytes never enter `localStorage`, `sessionStorage`, IndexedDB, the URL, query parameters, console logging, analytics, or error telemetry. The UI does not offer privileged private-body export; it downloads only the backend's redacted response. A failed export produces an inline error and no partial file.

## Component boundaries

`InvestigationsWorkspace.tsx` owns orchestration and query integration. Focused child components own title editing, conflict presentation, and export actions so causal-graph rendering remains independent. A small download utility converts already-authorized response strings into browser downloads and can be unit tested without the network.

API error handling must expose status and parsed detail to the workspace without weakening existing callers. If the current generic helper cannot do that safely, add a typed error class in `dashboard/src/app/api.ts` and preserve the existing message behavior.

## Accessibility and privacy

Inputs have persistent labels and validation text. Save, cancel, conflict, and export controls are keyboard reachable. The conflict panel uses an announced heading and moves focus when opened; closing it returns focus to the title control. Pending operations prevent duplicate submission but do not erase drafts. Filenames contain only the investigation identifier.

Privacy tests seed canaries in private message bodies and sensitive external-action fields. Canaries must be absent from the DOM, URLs, browser storage, console, error messages, and default downloads.

## Verification

- Unit tests for dirty-state transitions, typed 409 handling, filename/content type, Blob URL revocation, and failure cleanup.
- API tests retaining `expected_version`, 409, owner isolation, CSRF, and redacted export contracts.
- React tests for save success, validation, non-conflict failure, Reload, Save-as-new, and navigation with a dirty draft.
- Playwright tests using two browser contexts to create a real stale-version conflict.
- Playwright export tests that inspect downloaded bytes and scan DOM, URL, storage, IndexedDB, console, and network errors for canaries.
- Chromium keyboard, focus, screen-reader naming, loading, error, and narrow-layout checks.

## Acceptance evidence

Completion requires passing focused and full dashboard tests, backend workspace tests, conflict and privacy Playwright receipts in real Chromium, a production build, and manual confirmation that downloaded JSON/Markdown open correctly. Backend capability alone does not close the UI gap.

## Out of scope

- Automatic merging of concurrent edits.
- Editing replay-authoritative world state.
- Privileged export of private message bodies.
- Copying persisted evidence or hypotheses into the new investigation during title-conflict recovery.
