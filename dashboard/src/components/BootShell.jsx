/**
 * First paint for the one case the URL cannot resolve on its own.
 *
 * At `"/"` the local observatory and the hosted sign-in page are served from a
 * byte-identical document, so the shell that belongs there is only known once
 * `/api/v2/mode` answers.  Until then this renders the app's real chrome —
 * brand, title and an announced pending state — instead of a blank page.
 *
 * It is drawn on the civic paper ground that `civic-weather-room.css` gives
 * `html, body, #root`, so it is the same surface the observatory settles onto
 * and there is no flash between the two.  It deliberately shows no world data:
 * nothing here is a placeholder value.
 */
export function BootShell() {
  return <main
    className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-6 py-16"
    aria-busy="true"
  >
    <div>
      <p className="text-xs font-bold tracking-[.18em] text-[var(--civic-cobalt)] uppercase">
        Agent Economy
      </p>
      <h1 className="mt-3 text-4xl font-semibold text-[var(--civic-navy)]">
        Observatory
      </h1>
      <p role="status" className="mt-4 text-sm leading-relaxed text-[var(--civic-muted)]">
        Opening this workspace. The server is being asked which deployment this
        is; the observatory appears as soon as it answers.
      </p>
    </div>
    {/* Unlabelled on purpose: "/" may resolve to either shell, so the skeleton
        names no section and states no value it has not received. */}
    <div className="grid gap-3 sm:grid-cols-3" aria-hidden="true">
      {[0, 1, 2].map(index => <div
        key={index}
        className="rounded-xl border border-[var(--civic-rule)] bg-[var(--civic-white)] p-4"
      >
        <div className="h-2 w-1/3 animate-pulse rounded bg-[var(--civic-rule)]" />
        <div className="mt-4 h-2 w-full animate-pulse rounded bg-[var(--civic-rule)]" />
        <div className="mt-2 h-2 w-2/3 animate-pulse rounded bg-[var(--civic-rule)]" />
      </div>)}
    </div>
  </main>;
}
