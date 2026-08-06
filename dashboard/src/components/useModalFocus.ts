import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = [
  "button:not([disabled]):not([tabindex='-1'])",
  "[href]:not([tabindex='-1'])",
  "input:not([disabled]):not([tabindex='-1'])",
  "select:not([disabled]):not([tabindex='-1'])",
  "textarea:not([disabled]):not([tabindex='-1'])",
  "iframe:not([tabindex='-1'])",
  "summary:not([tabindex='-1'])",
  "audio[controls]:not([tabindex='-1'])",
  "video[controls]:not([tabindex='-1'])",
  "[contenteditable]:not([contenteditable='false']):not([tabindex='-1'])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

export function isTabbableElement(element: HTMLElement): boolean {
  const implicitContentEditable = element.matches(
    "[contenteditable]:not([contenteditable='false']):not([tabindex])",
  );
  if ((!implicitContentEditable && element.tabIndex < 0) || element.matches(":disabled")) return false;
  const style = getComputedStyle(element);
  return style.display !== "none"
    && style.visibility !== "hidden"
    && element.getClientRects().length > 0;
}

function tabbableElements(dialog: HTMLElement): HTMLElement[] {
  const candidates = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)]
    .filter(isTabbableElement);
  const radios = candidates.filter((element): element is HTMLInputElement => (
    element instanceof HTMLInputElement && element.type === "radio" && Boolean(element.name)
  ));
  return candidates.filter(element => {
    if (!(element instanceof HTMLInputElement)
      || element.type !== "radio"
      || !element.name) return true;
    const group = radios.filter(candidate => (
      candidate.name === element.name && candidate.form === element.form
    ));
    return element === (group.find(candidate => candidate.checked) || group[0]);
  });
}

type ModalFocusOptions = {
  active?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  returnFocusRef?: RefObject<HTMLElement | null>;
  onEscape(): void;
};

export function useModalFocus({
  active = true, initialFocusRef, returnFocusRef, onEscape,
}: ModalFocusOptions) {
  const dialogRef = useRef<HTMLElement>(null);
  const escapeRef = useRef(onEscape);
  escapeRef.current = onEscape;

  useEffect(() => {
    if (!active || !dialogRef.current) return;
    const dialog = dialogRef.current;
    const hadTabIndex = dialog.hasAttribute("tabindex");
    if (!hadTabIndex) dialog.tabIndex = -1;
    const previous = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    // A caller-provided target may deliberately have tabIndex=-1 so focus can
    // start on a heading without adding that heading to the Tab sequence. It
    // still has to be a live descendant of this dialog.
    const initialTarget = initialFocusRef?.current;
    const focusTarget = initialTarget?.isConnected && dialog.contains(initialTarget)
      ? initialTarget
      : (tabbableElements(dialog)[0] || dialog);
    focusTarget.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        escapeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = tabbableElements(dialog);
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1)!;
      const activeElement = document.activeElement;
      const activeIsTabbable = activeElement instanceof HTMLElement
        && focusable.includes(activeElement);
      if (event.shiftKey && (activeElement === first || !activeIsTabbable)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || !activeIsTabbable)) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      if (!hadTabIndex) dialog.removeAttribute("tabindex");
      const requestedReturn = returnFocusRef?.current;
      const returnTarget = requestedReturn?.isConnected
        ? requestedReturn
        : (previous?.isConnected ? previous : null);
      returnTarget?.focus();
    };
  }, [active, initialFocusRef, returnFocusRef]);

  return dialogRef;
}
