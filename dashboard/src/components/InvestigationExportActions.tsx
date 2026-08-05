import { useState } from "react";
import { workspaceApi } from "../app/api";
import { downloadText } from "../lib/downloadText";

type ExportResponse = {
  json: Record<string, unknown>;
  markdown: string;
};

export function InvestigationExportActions({ investigationId }: { investigationId: string }) {
  const [pending, setPending] = useState<"json" | "md" | null>(null);
  const [error, setError] = useState("");

  const download = async (format: "json" | "md") => {
    if (pending) return;
    setPending(format);
    setError("");
    try {
      const payload = await workspaceApi<ExportResponse>(
        `/api/v2/operator/investigations/${encodeURIComponent(investigationId)}/export`,
      );
      const jsonText = JSON.stringify(payload.json, null, 2) + "\n";
      downloadText({
        documentRef: document,
        urlApi: URL,
        BlobCtor: Blob,
        filename: `${investigationId}.${format}`,
        mimeType: format === "json" ? "application/json" : "text/markdown;charset=utf-8",
        text: format === "json" ? jsonText : payload.markdown,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Investigation export failed.");
    } finally {
      setPending(null);
    }
  };

  return <div className="world-os-export-actions">
    <button className="button" type="button" disabled={Boolean(pending)}
      onClick={() => download("json")}>Download JSON</button>
    <button className="button" type="button" disabled={Boolean(pending)}
      onClick={() => download("md")}>Download Markdown</button>
    {error && <p className="world-os-form-error" role="alert">Export failed: {error}</p>}
  </div>;
}
