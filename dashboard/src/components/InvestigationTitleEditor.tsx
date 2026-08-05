import type { RefObject } from "react";
import {
  investigationTitleError, normalizedInvestigationTitle,
} from "../workspaces/investigationState";

type InvestigationTitleEditorProps = {
  title: string;
  serverTitle: string;
  version: number;
  pending: boolean;
  blocked?: boolean;
  error: string;
  inputRef?: RefObject<HTMLInputElement | null>;
  onChange(title: string): void;
  onSave(): void;
  onCancel(): void;
};

export function InvestigationTitleEditor({
  title, serverTitle, version, pending, blocked = false, error, inputRef, onChange, onSave, onCancel,
}: InvestigationTitleEditorProps) {
  const validation = investigationTitleError(title);
  const unchanged = normalizedInvestigationTitle(title)
    === normalizedInvestigationTitle(serverTitle);
  return <form className="world-os-title-editor" onSubmit={event => {
    event.preventDefault();
    if (!validation && !unchanged && !pending && !blocked) onSave();
  }}>
    <label htmlFor="investigation-title">Investigation title</label>
    <div className="world-os-title-editor__row">
      <input id="investigation-title" ref={inputRef} value={title} maxLength={160}
        aria-describedby="investigation-title-guidance"
        aria-invalid={Boolean(validation || error)}
        onChange={event => onChange(event.target.value)} />
      <button className="button button-primary" type="submit"
        disabled={Boolean(validation) || unchanged || pending || blocked}>Save</button>
      <button className="button" type="button" disabled={unchanged || pending}
        onClick={onCancel}>Cancel</button>
    </div>
    <div id="investigation-title-guidance" className={validation || error ? "world-os-form-error" : "world-os-form-guidance"} role={validation || error ? "alert" : undefined}>
      {error || validation || (blocked
        ? "Resolve the server version conflict before saving this draft."
        : pending
          ? "Saving…"
          : `Saved as version ${version}. Titles are limited to 160 characters.`)}
    </div>
  </form>;
}
