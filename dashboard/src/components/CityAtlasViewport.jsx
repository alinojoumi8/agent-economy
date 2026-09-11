import { useRef } from "react";
import { cityCameraScale, normalizeCityCamera } from "../lib/cityCamera.js";

/** Pan the sheet on a mouse drag; touch scrolling and marker clicks retain their ordinary behavior. */
export function CityAtlasViewport({ camera, onCameraChange, disabled, children }) {
  const drag = useRef(null);
  const suppressClickUntil = useRef(0);
  const scale = cityCameraScale(camera);
  return <div className="city-atlas-viewport" data-testid="city-atlas-viewport"
    data-camera={`${camera.x},${camera.y},${camera.zoom}`}
    onPointerDown={event => {
      if (disabled || event.button !== 0 || event.pointerType === "touch" || event.target.closest("button")) return;
      const rect = event.currentTarget.getBoundingClientRect();
      drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY,
        camera, width: rect.width, height: rect.height, moved: false };
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={event => {
      const start = drag.current;
      if (!start || start.id !== event.pointerId) return;
      const dx = event.clientX - start.x, dy = event.clientY - start.y;
      if (!start.moved && Math.hypot(dx, dy) < 4) return;
      const next = normalizeCityCamera({ ...start.camera,
        x: start.camera.x - dx / start.width / cityCameraScale(start.camera) * 100,
        y: start.camera.y - dy / start.height / cityCameraScale(start.camera) * 100 });
      onCameraChange(next, { replace: start.moved });
      start.moved = true;
    }}
    onPointerUp={event => {
      if (drag.current?.moved) suppressClickUntil.current = performance.now() + 250;
      drag.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    }}
    onPointerCancel={() => { drag.current = null; }}
    onLostPointerCapture={() => { drag.current = null; }}
    onClickCapture={event => {
      if (performance.now() < suppressClickUntil.current) { event.stopPropagation(); event.preventDefault(); }
    }}>
    <div className="city-atlas-plane" style={{
      "--city-camera-inverse": 1 / scale,
      transform: `translate(${50 - camera.x * scale}%, ${50 - camera.y * scale}%) scale(${scale})`,
    }}>{children}</div>
  </div>;
}
