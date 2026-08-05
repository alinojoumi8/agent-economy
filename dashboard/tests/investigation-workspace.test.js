import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { workspaceErrorMessage } from "../src/app/api.ts";
import {
  acceptSavedInvestigation,
  cancelInvestigationEdit,
  createInvestigationDraft,
  editInvestigationTitle,
  investigationTitleError,
  investigationUpdatePayload,
  openInvestigationConflict,
  reloadInvestigationConflict,
} from "../src/workspaces/investigationState.js";

test("workspace API preserves HTTP status without exposing response internals", async () => {
  const source = await readFile(new URL("../src/app/api.ts", import.meta.url), "utf8");
  assert.match(source, /export class WorkspaceApiError extends Error/);
  assert.match(source, /new WorkspaceApiError\(\s*response\.status/s);
  assert.doesNotMatch(source, /JSON\.stringify\(payload\)/);

  assert.equal(
    workspaceErrorMessage({ detail: "investigation version conflict" }, 409),
    "investigation version conflict",
  );
  assert.equal(workspaceErrorMessage({}, 503), "Workspace request failed (503)");
});

test("investigation title drafts preserve local work across a conflict", () => {
  const serverV1 = {
    id: "inv-1", title: "Original", version: 1, run_id: "run-demo",
    fork_id: null, pinned_tick: 6, query: { relation: "cited" }, layout: null,
  };
  let state = createInvestigationDraft(serverV1);
  state = editInvestigationTitle(state, "Local draft");
  assert.equal(state.dirty, true);
  assert.equal(state.server.version, 1);

  state = openInvestigationConflict(state, {
    ...serverV1, title: "Remote title", version: 2,
  });
  assert.equal(state.titleDraft, "Local draft");
  assert.equal(state.server.version, 1);
  assert.equal(state.conflict.server.title, "Remote title");
  assert.equal(state.conflict.submittedVersion, 1);

  state = reloadInvestigationConflict(state);
  assert.equal(state.titleDraft, "Remote title");
  assert.equal(state.server.version, 2);
  assert.equal(state.dirty, false);
  assert.equal(state.conflict, null);
});

test("investigation draft transitions validate, cancel, save, and switch records", () => {
  const first = { id: "inv-1", title: "Original", version: 1 };
  const saved = { id: "inv-1", title: "Saved", version: 2 };
  const second = { id: "inv-2", title: "Second", version: 1 };
  let state = editInvestigationTitle(createInvestigationDraft(first), "Saved");

  assert.equal(investigationTitleError("   "), "Title is required.");
  assert.equal(investigationTitleError("x".repeat(160)), "");
  assert.equal(investigationTitleError("x".repeat(161)), "Title must be 160 characters or fewer.");
  assert.equal(cancelInvestigationEdit(state).titleDraft, "Original");

  state = acceptSavedInvestigation(state, saved);
  assert.deepEqual(state, {
    server: saved, titleDraft: "Saved", dirty: false, conflict: null, error: "",
  });
  assert.deepEqual(createInvestigationDraft(second).server, second);
});

test("investigation title editor submits the authoritative expected version", async () => {
  const editorSource = await readFile(
    new URL("../src/components/InvestigationTitleEditor.tsx", import.meta.url), "utf8",
  );
  const workspaceSource = await readFile(
    new URL("../src/workspaces/InvestigationsWorkspace.tsx", import.meta.url), "utf8",
  );
  assert.match(editorSource, /htmlFor="investigation-title"/);
  assert.match(editorSource, /maxLength=\{160\}/);
  assert.match(editorSource, />Save</);
  assert.match(editorSource, />Cancel</);
  assert.match(workspaceSource, /expected_version:\s*draft\.server\.version/);

  const state = editInvestigationTitle(createInvestigationDraft({
    id: "inv-1", title: "Original", version: 1,
  }), "Local draft");
  assert.deepEqual(investigationUpdatePayload(state), {
    expected_version: 1,
    title: "Local draft",
  });
});
