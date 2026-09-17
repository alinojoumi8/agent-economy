const SAFE_DOWNLOAD_NAME = /^[A-Za-z0-9._-]+\.(json|md)$/;
// Firefox and Safari start the download after click() returns, so revoking the
// object URL synchronously can cancel it. A second is generous for a local blob.
export const REVOKE_DELAY_MS = 1000;

export function downloadText({
  documentRef = document,
  urlApi = URL,
  BlobCtor = Blob,
  schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
  filename,
  mimeType,
  text,
}) {
  if (!SAFE_DOWNLOAD_NAME.test(String(filename || ""))) {
    throw new Error("Download requires a safe JSON or Markdown filename.");
  }
  const blob = new BlobCtor([String(text)], { type: String(mimeType) });
  const objectUrl = urlApi.createObjectURL(blob);
  let anchor = null;
  let clicked = false;
  try {
    anchor = documentRef.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.hidden = true;
    documentRef.body.appendChild(anchor);
    anchor.click();
    clicked = true;
  } finally {
    anchor?.remove();
    // Only a click that returned can have started a download; a click that threw
    // leaves nothing to wait for, so its URL is released at once.
    if (clicked) schedule(() => urlApi.revokeObjectURL(objectUrl), REVOKE_DELAY_MS);
    else urlApi.revokeObjectURL(objectUrl);
  }
}
