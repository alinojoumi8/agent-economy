import React, { useRef } from "react";
import { createRoot } from "react-dom/client";

import { useModalFocus } from "../../../src/components/useModalFocus";

function ModalFocusHarness() {
  const detachedInitialFocus = useRef(document.createElement("button"));
  const dialogRef = useModalFocus({
    initialFocusRef: detachedInitialFocus,
    onEscape: () => {},
  });
  return <section ref={dialogRef} role="dialog" aria-label="Focus harness">
    <button type="button">Fallback action</button>
  </section>;
}

export function mountModalFocusHarness(container) {
  createRoot(container).render(<ModalFocusHarness />);
}
