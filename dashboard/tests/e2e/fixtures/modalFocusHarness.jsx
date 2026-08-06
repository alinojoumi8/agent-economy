import React, { useRef } from "react";
import { createRoot } from "react-dom/client";

import { useModalFocus } from "../../../src/components/useModalFocus";

const roots = new WeakMap();

function ModalFocusHarness({ connectedInitial = false, disconnectedReturn = false }) {
  const detachedInitialFocus = useRef(document.createElement("button"));
  const connectedInitialFocus = useRef(null);
  const disconnectedReturnFocus = useRef(document.createElement("button"));
  const dialogRef = useModalFocus({
    initialFocusRef: connectedInitial ? connectedInitialFocus : detachedInitialFocus,
    returnFocusRef: disconnectedReturn ? disconnectedReturnFocus : undefined,
    onEscape: () => {},
  });
  return <section ref={dialogRef} role="dialog" aria-label="Focus harness">
    <button type="button">Fallback action</button>
    <label><input type="radio" name="focus-choice" defaultChecked /> Primary choice</label>
    <label><input type="radio" name="focus-choice" /> Alternate choice</label>
    <h2 ref={connectedInitialFocus} tabIndex={-1}>Initial heading</h2>
  </section>;
}

export function mountModalFocusHarness(container, options = {}) {
  const root = createRoot(container);
  roots.set(container, root);
  root.render(<ModalFocusHarness {...options} />);
}

export function unmountModalFocusHarness(container) {
  roots.get(container)?.unmount();
  roots.delete(container);
}
