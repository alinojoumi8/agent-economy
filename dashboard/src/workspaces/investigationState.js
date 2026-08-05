export function investigationTitleError(title) {
  const value = String(title ?? "");
  if (!value.trim()) return "Title is required.";
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
  return {
    ...state,
    titleDraft: title,
    dirty: title !== state.server.title,
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
    title: state.titleDraft.trim(),
  };
}
