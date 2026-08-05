export function normalizedInvestigationTitle(title) {
  return String(title ?? "").trim();
}

export function investigationTitleError(title) {
  const value = normalizedInvestigationTitle(title);
  if (!value) return "Title is required.";
  if (value.length > 160) return "Title must be 160 characters or fewer.";
  return "";
}

export function createInvestigationDraft(record) {
  return {
    server: record,
    titleDraft: record.title,
    dirty: false,
    conflict: null,
    error: "",
  };
}

export function editInvestigationTitle(state, title) {
  const titleDraft = String(title ?? "");
  return {
    ...state,
    titleDraft,
    dirty: normalizedInvestigationTitle(titleDraft)
      !== normalizedInvestigationTitle(state.server.title),
    error: "",
  };
}

export function cancelInvestigationEdit(state) {
  return {
    ...state,
    titleDraft: state.server.title,
    dirty: false,
    conflict: null,
    error: "",
  };
}

export function acceptSavedInvestigation(_state, record) {
  return createInvestigationDraft(record);
}

export function openInvestigationConflict(state, record) {
  return {
    ...state,
    conflict: {
      server: record,
      submittedVersion: state.server.version,
      open: true,
    },
    error: "",
  };
}

export function reloadInvestigationConflict(state) {
  if (!state.conflict) return state;
  return createInvestigationDraft(state.conflict.server);
}

export function investigationUpdatePayload(state) {
  return {
    expected_version: state.server.version,
    title: normalizedInvestigationTitle(state.titleDraft),
  };
}

export function continueInvestigationConflict(state) {
  if (!state.conflict) return state;
  const server = state.conflict.server;
  return {
    ...state,
    server,
    dirty: normalizedInvestigationTitle(state.titleDraft)
      !== normalizedInvestigationTitle(server.title),
    conflict: null,
    error: "",
  };
}

export function reopenInvestigationConflict(state) {
  if (!state.conflict) return state;
  return { ...state, conflict: { ...state.conflict, open: true } };
}

export function saveInvestigationAsNewPayload(state) {
  if (!state.conflict) throw new Error("No investigation conflict is available.");
  const validation = investigationTitleError(state.titleDraft);
  if (validation) throw new Error(validation);
  const current = state.conflict.server;
  return {
    title: normalizedInvestigationTitle(state.titleDraft),
    fork_id: current.fork_id ?? null,
    pinned_tick: current.pinned_tick ?? null,
    query: current.query || {},
    layout: current.layout || {},
  };
}

export function requestInvestigationSaveAsNew(state, mutate, reportError) {
  const validation = investigationTitleError(state?.titleDraft);
  if (validation) {
    reportError(validation);
    return false;
  }
  mutate(state);
  return true;
}
