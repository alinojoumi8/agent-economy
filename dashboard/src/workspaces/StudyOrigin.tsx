export type OriginDetails = { kind: string; tick: number; continuation_window: number[]; independent_worlds: number;
  sources: Array<{ seed: number; run_id: string | null; database_sha256: string | null; receipt_sha256: string }> };

export function StudyOrigin({ origin }: { origin?: OriginDetails }) {
  if (!origin) return null;
  const saved = origin.kind === "verified_checkpoints";
  return <section className="study-origin" aria-label="Declared initial conditions">
    <h4>{saved ? "Saved-world initial conditions" : "Fresh-world initial conditions"}</h4>
    <p>{origin.independent_worlds} independent initial world{origin.independent_worlds === 1 ? "" : "s"} · {saved ? `saved day ${origin.tick}` : "fresh genesis"} · new execution days {origin.continuation_window.join("–")}.</p>
    {saved && <>
      <p>Each treatment/control pair starts from the same admitted state. Replay verifies the new interval; earlier history is inherited. Source seeds are retained.</p>
      <details><summary>Selected source identities</summary>
        <ul>{origin.sources.map(source => <li key={source.seed}>Seed {source.seed} · run <code>{source.run_id ?? "Unavailable"}</code>
          <p>Database SHA-256: <code>{source.database_sha256 ?? "Unavailable"}</code><br />Admission receipt: <code>{source.receipt_sha256}</code></p></li>)}</ul>
      </details>
    </>}
  </section>;
}
