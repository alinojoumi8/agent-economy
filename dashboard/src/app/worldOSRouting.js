export function worldOSIndexWorkspace(pathname) {
  return /^\/commons(?:\/|$)/.test(String(pathname || ""))
    ? "commons"
    : "overview";
}
