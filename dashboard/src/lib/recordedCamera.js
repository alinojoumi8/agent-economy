import { cityCameraScale, normalizeCityCamera, serializeCityCamera } from "./cityCamera.js";

/** Invert the recorded renderer's fit projection into the shared 0–100 city plane. */
export function recordedPointCamera(projection, point, zoom) {
  return normalizeCityCamera({
    x: (projection.minX + (point.x - projection.left) / projection.scaleX) * 100,
    y: (projection.minY + (point.y - projection.top) / projection.scaleY) * 100,
    zoom,
  });
}

/** One affine camera for the whole recorded sheet; it never changes recorded anchors.
 * @param {{x:number,y:number}|null} followedPoint */
export function recordedCameraTransform(projection, width, height, camera, followedPoint = null) {
  const scale = cityCameraScale(camera);
  const center = followedPoint || (serializeCityCamera(camera)
    ? projection.project(camera.x / 100, camera.y / 100) : { x: width / 2, y: height / 2 });
  return { x: width / 2 - center.x * scale, y: height / 2 - center.y * scale, scale,
    camera: recordedPointCamera(projection, center, camera.zoom) };
}
