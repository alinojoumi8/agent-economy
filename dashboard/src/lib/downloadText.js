const SAFE_DOWNLOAD_NAME = /^[A-Za-z0-9._-]+\.(json|md)$/;

export function downloadText({
  documentRef = document,
  urlApi = URL,
  BlobCtor = Blob,
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
  try {
    anchor = documentRef.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.hidden = true;
    documentRef.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor?.remove();
    urlApi.revokeObjectURL(objectUrl);
  }
}
