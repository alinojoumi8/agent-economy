import { useRef, type RefObject } from "react";
import { investigationTitleError } from "../workspaces/investigationState";
import { useModalFocus } from "./useModalFocus";

type InvestigationConflictDialogProps = {
  draftTitle: string;
  serverTitle: string;
  serverVersion: number;
  pending: boolean;
  canSaveAsNew?: boolean;
  returnFocusRef?: RefObject<HTMLInputElement | null>;
  onReload(): void;
  onSaveAsNew(): void;
  onContinue(): void;
};

export function InvestigationConflictDialog({
  draftTitle, serverTitle, serverVersion, pending, canSaveAsNew = true, returnFocusRef,
  onReload, onSaveAsNew, onContinue,
}: InvestigationConflictDialogProps) {
  const validation = investigationTitleError(draftTitle);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dialogRef = useModalFocus({
    initialFocusRef: headingRef,
    returnFocusRef,
    onEscape: () => { if (!pending) onContinue(); },
  });

  return <div className="world-os-dialog-backdrop">
    <section ref={dialogRef} className="world-os-dialog world-os-conflict-dialog"
      role="dialog" aria-modal="true" aria-labelledby="investigation-conflict-title"
      tabIndex={-1}>
      <p className="world-os-kicker">Optimistic write stopped</p>
      <h3 id="investigation-conflict-title" ref={headingRef} tabIndex={-1}>Investigation changed on the server</h3>
      <div className="world-os-conflict-compare">
        <p>Your draft: <strong>{draftTitle}</strong></p>
        <p>Server version {serverVersion}: <strong>{serverTitle}</strong></p>
      </div>
      <p>No automatic merge or overwrite occurred. Evidence and hypotheses stay with the original investigation if you save this title as a new investigation.</p>
      {validation && <p className="world-os-form-error" role="alert">{validation}</p>}
      <div className="world-os-dialog-actions">
        <button className="button button-primary" type="button" disabled={pending} onClick={onReload}>Reload server version</button>
        <button className="button" type="button" disabled={pending || !canSaveAsNew || Boolean(validation)} onClick={onSaveAsNew}>Save draft as new investigation</button>
        <button className="button" type="button" disabled={pending} onClick={onContinue}>Continue editing</button>
      </div>
    </section>
  </div>;
}
