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
  return [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)]
    .filter(isTabbableElement);
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
    // start on a heading without adding that heading to the Tab sequence.
    (initialFocusRef?.current || tabbableElements(dialog)[0] || dialog).focus();

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
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      if (!hadTabIndex) dialog.removeAttribute("tabindex");
      (returnFocusRef?.current || previous)?.focus();
    };
  }, [active, initialFocusRef, returnFocusRef]);

  return dialogRef;
}
