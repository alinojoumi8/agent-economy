import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CITY_CAMERA } from "../src/lib/cityCamera.js";
import { recordedCameraTransform, recordedPointCamera } from "../src/lib/recordedCamera.js";
import { fitProjection } from "../src/lib/liveCity.js";

test("recorded camera fits by default and centers the same recorded point under zoom", () => {
  const projection = fitProjection({ minX: .1, minY: .2, maxX: .8, maxY: .9 }, 800, 520,
    { left: 68, right: 68, top: 40, bottom: 40 });
  const original = recordedCameraTransform(projection, 800, 520, DEFAULT_CITY_CAMERA);
  assert.equal(original.x, 0); assert.equal(original.y, 0); assert.equal(original.scale, 1);
  const followed = { ...projection.project(.3, .4), offsetX: 0, offsetY: 0 };
  const zoomed = recordedCameraTransform(projection, 800, 520, { ...DEFAULT_CITY_CAMERA, zoom: 4.05 }, followed);
  assert.equal(zoomed.scale, 2);
  assert.equal(followed.x * zoomed.scale + zoomed.x, 400);
  assert.equal(followed.y * zoomed.scale + zoomed.y, 260);
  assert.deepEqual(zoomed.camera, { x: 30, y: 40, zoom: 4.05 });
  const stopped = recordedCameraTransform(projection, 800, 520, zoomed.camera);
  assert.ok(Math.abs(stopped.x - zoomed.x) < 1e-9);
  assert.ok(Math.abs(stopped.y - zoomed.y) < 1e-9);
  assert.deepEqual(recordedPointCamera(projection, projection.project(.7, .8), 3.4), { x: 70, y: 80, zoom: 3.4 });
});
