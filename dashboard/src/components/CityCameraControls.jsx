import { DEFAULT_CITY_CAMERA } from "../lib/cityCamera.js";
import "./city-camera.css";

/** All camera actions affect observer state only. Each renderer supplies its current camera. */
export function CityCameraControls({ getCamera, onCameraChange, onFocus, canFocus, disabled = false }) {
  const pan = (x, y) => {
    const camera = getCamera();
    onCameraChange({ ...camera, x: camera.x + x, y: camera.y + y });
  };
  const zoom = delta => {
    const camera = getCamera();
    onCameraChange({ ...camera, zoom: camera.zoom + delta }, { keepFollow: true });
  };
  return <fieldset className="city-camera" disabled={disabled} aria-label="City camera controls">
    <legend className="sr-only">City camera controls</legend>
    <button type="button" onClick={() => zoom(.35)} aria-label="Zoom into city">+</button>
    <button type="button" onClick={() => zoom(-.35)} aria-label="Zoom out of city">−</button>
    <button type="button" onClick={() => onCameraChange(DEFAULT_CITY_CAMERA)}>Reset camera</button>
    <button type="button" disabled={!canFocus} onClick={onFocus}>Focus selection</button>
    <button type="button" aria-label="Pan city left" onClick={() => pan(-5, 0)}>←</button>
    <button type="button" aria-label="Pan city right" onClick={() => pan(5, 0)}>→</button>
    <button type="button" aria-label="Pan city up" onClick={() => pan(0, -5)}>↑</button>
    <button type="button" aria-label="Pan city down" onClick={() => pan(0, 5)}>↓</button>
  </fieldset>;
}
