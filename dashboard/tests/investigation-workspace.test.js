import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { workspaceErrorMessage } from "../src/app/api.ts";
import { downloadText } from "../src/lib/downloadText.js";
import {
  acceptSavedInvestigation,
  cancelInvestigationEdit,
  createInvestigationDraft,
  editInvestigationTitle,
  investigationTitleError,
  investigationUpdatePayload,
  openInvestigationConflict,
  reloadInvestigationConflict,
  saveInvestigationAsNewPayload,
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

test("version conflict renders explicit recovery without a hidden retry", async () => {
  const vite = await createServer({
    appType: "custom", logLevel: "silent", server: { middlewareMode: true },
  });
  try {
    const { InvestigationConflictDialog } = await vite.ssrLoadModule(
      "/src/components/InvestigationConflictDialog.tsx",
    );
    const markup = renderToStaticMarkup(React.createElement(InvestigationConflictDialog, {
      draftTitle: "Local draft", serverTitle: "Remote title", serverVersion: 2,
      pending: false, onReload: () => {}, onSaveAsNew: () => {}, onContinue: () => {},
    }));
    assert.match(markup, /Your draft:[^<]*<[^>]*>Local draft/);
    assert.match(markup, /Server version 2:[^<]*<[^>]*>Remote title/);
    assert.match(markup, /Reload server version/);
    assert.match(markup, /Save draft as new investigation/);
    assert.match(markup, /Continue editing/);
  } finally {
    await vite.close();
  }

  const workspaceSource = await readFile(
    new URL("../src/workspaces/InvestigationsWorkspace.tsx", import.meta.url), "utf8",
  );
  assert.match(workspaceSource, /reason instanceof WorkspaceApiError/);
  assert.match(workspaceSource, /reason\.status === 409/);
  assert.equal((workspaceSource.match(/method:\s*"PATCH"/g) || []).length, 1);
});

test("save-as-new copies context but never evidence or hypotheses", () => {
  const server = {
    id: "inv-1", title: "Remote title", version: 2, run_id: "run-demo",
    fork_id: "fork-1", pinned_tick: 6, query: { relation: "cited" },
    layout: { left: 320 }, items: [{ id: "item-private" }],
    hypotheses: [{ id: "hyp-private" }],
  };
  let state = editInvestigationTitle(createInvestigationDraft({
    ...server, title: "Original", version: 1,
  }), "Local draft");
  state = openInvestigationConflict(state, server);
  assert.deepEqual(saveInvestigationAsNewPayload(state), {
    title: "Local draft", fork_id: "fork-1", pinned_tick: 6,
    query: { relation: "cited" }, layout: { left: 320 },
  });
});

test("text downloads click once and always revoke their object URL", () => {
  const createdBlobs = [];
  const revokedUrls = [];
  let appended = null;
  const anchor = {
    download: "", href: "", hidden: false, clicks: 0, removed: 0,
    click() { this.clicks += 1; },
    remove() { this.removed += 1; },
  };
  class FakeBlob {
    constructor(parts, options) {
      this.parts = parts;
      this.options = options;
      createdBlobs.push(this);
    }
  }
  const documentRef = {
    createElement(tag) { assert.equal(tag, "a"); return anchor; },
    body: { appendChild(value) { appended = value; } },
  };
  const urlApi = {
    createObjectURL(blob) { assert.equal(blob, createdBlobs[0]); return "blob:test"; },
    revokeObjectURL(url) { revokedUrls.push(url); },
  };

  downloadText({
    documentRef, urlApi, BlobCtor: FakeBlob, filename: "inv-1.json",
    mimeType: "application/json", text: "{\"safe\":true}\n",
  });
  assert.deepEqual(createdBlobs[0].parts, ["{\"safe\":true}\n"]);
  assert.deepEqual(createdBlobs[0].options, { type: "application/json" });
  assert.equal(anchor.download, "inv-1.json");
  assert.equal(anchor.clicks, 1);
  assert.equal(anchor.removed, 1);
  assert.equal(appended, anchor);
  assert.deepEqual(revokedUrls, ["blob:test"]);
});

test("text download cleanup survives click failure and rejects unsafe filenames", () => {
  let removed = 0;
  const revokedUrls = [];
  const documentRef = {
    createElement() { return {
      click() { throw new Error("blocked click"); },
      remove() { removed += 1; },
    }; },
    body: { appendChild() {} },
  };
  const urlApi = {
    createObjectURL() { return "blob:failure"; },
    revokeObjectURL(url) { revokedUrls.push(url); },
  };
  class FakeBlob {}
  assert.throws(() => downloadText({
    documentRef, urlApi, BlobCtor: FakeBlob, filename: "inv-1.md",
    mimeType: "text/markdown;charset=utf-8", text: "# Safe\n",
  }), /blocked click/);
  assert.equal(removed, 1);
  assert.deepEqual(revokedUrls, ["blob:failure"]);
  assert.throws(() => downloadText({
    documentRef, urlApi, BlobCtor: FakeBlob, filename: "../unsafe.json",
    mimeType: "application/json", text: "{}",
  }), /safe JSON or Markdown filename/);
});

test("investigation export controls expose only backend-redacted JSON and Markdown", async () => {
  const vite = await createServer({
    appType: "custom", logLevel: "silent", server: { middlewareMode: true },
  });
  try {
    const { InvestigationExportActions } = await vite.ssrLoadModule(
      "/src/components/InvestigationExportActions.tsx",
    );
    const markup = renderToStaticMarkup(React.createElement(
      InvestigationExportActions, { investigationId: "inv-1" },
    ));
    assert.match(markup, /Download JSON/);
    assert.match(markup, /Download Markdown/);
  } finally {
    await vite.close();
  }
  const source = await readFile(
    new URL("../src/components/InvestigationExportActions.tsx", import.meta.url), "utf8",
  );
  assert.match(source, /JSON\.stringify\(payload\.json, null, 2\) \+ "\\n"/);
  assert.match(source, /application\/json/);
  assert.match(source, /text\/markdown;charset=utf-8/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\./);
});
