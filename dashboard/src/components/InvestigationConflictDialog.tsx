import { useEffect, useRef, type RefObject } from "react";

type InvestigationConflictDialogProps = {
  draftTitle: string;
  serverTitle: string;
  serverVersion: number;
  pending: boolean;
  returnFocusRef?: RefObject<HTMLInputElement | null>;
  onReload(): void;
  onSaveAsNew(): void;
  onContinue(): void;
};

export function InvestigationConflictDialog({
  draftTitle, serverTitle, serverVersion, pending, returnFocusRef,
  onReload, onSaveAsNew, onContinue,
}: InvestigationConflictDialogProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus();
    return () => (returnFocusRef?.current || previous)?.focus();
  }, [returnFocusRef]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onContinue();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
      "button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ) || [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return <div className="world-os-dialog-backdrop">
    <section ref={dialogRef} className="world-os-dialog world-os-conflict-dialog"
      role="dialog" aria-modal="true" aria-labelledby="investigation-conflict-title"
      onKeyDown={onKeyDown}>
      <p className="world-os-kicker">Optimistic write stopped</p>
      <h3 id="investigation-conflict-title" ref={headingRef} tabIndex={-1}>Investigation changed on the server</h3>
      <div className="world-os-conflict-compare">
        <p>Your draft: <strong>{draftTitle}</strong></p>
        <p>Server version {serverVersion}: <strong>{serverTitle}</strong></p>
      </div>
      <p>No automatic merge or overwrite occurred. Evidence and hypotheses stay with the original investigation if you save this title as a new investigation.</p>
      <div className="world-os-dialog-actions">
        <button className="button button-primary" type="button" disabled={pending} onClick={onReload}>Reload server version</button>
        <button className="button" type="button" disabled={pending} onClick={onSaveAsNew}>Save draft as new investigation</button>
        <button className="button" type="button" disabled={pending} onClick={onContinue}>Continue editing</button>
      </div>
    </section>
  </div>;
}
