import { useState } from "react";
import { budgetState, number } from "../api";
import { clientLog } from "../logging.js";
import { inferenceMode } from "../lib/inferenceMode.js";
import worldOsEmblem from "../assets/world-os-emblem.png";
import { Badge } from "./ui";
import { CitizenMenu } from "./CitizenMenu";

export function runControlState(status, busy = "") {
  const running = Boolean(
    status?.running || status?.status === "running" || busy === "start" || busy === "step"
  );
  const interruptibleBusy = busy === "start" || busy === "step";
  return {
    running,
    displayStatus: running ? "running" : status?.status || "loading",
    pauseDisabled: !running || Boolean(busy && !interruptibleBusy),
    stopDisabled: status?.status === "halted" || Boolean(busy && !interruptibleBusy),
  };
}

export function RunHeader({ status, participant, connected, loading, act, onShock, onReplay,
  hosted = false, canControl = true }) {
  const [busy, setBusy] = useState("");
  const { running, displayStatus, pauseDisabled, stopDisabled } = runControlState(status, busy);
  const terminal = status?.status === "halted";
  const participantActive = Boolean(participant?.active);
  const participantReady = Boolean(participant?.queued_action);
  const limitReached = status?.remaining_ticks === 0;
  const { spend, cap, capped, fraction } = budgetState(status?.governor);
  const inference = inferenceMode(status?.provider_readiness);

  async function action(name, path, body) {
    setBusy(name);
    try {
      await act(path, body);
    } catch (reason) {
      clientLog("dashboard.control.failed", {
        control: name, path,
        error_type: reason?.constructor?.name || typeof reason,
        error: reason instanceof Error ? reason.message : String(reason),
      }, "error");
    } finally { setBusy(""); }
  }

  return (
    <header className="civic-run-header sticky top-0 z-50 border-b border-mint-300/10 bg-ink-950/90 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-3 px-3 py-2.5 sm:px-5">
        <div className="civic-run-header__brand mr-2">
          <img src={worldOsEmblem} alt="" />
          <div>
            <div className="eyebrow">Agent Economy</div>
            <div className="mt-0.5 flex items-center gap-2 text-sm font-semibold tracking-wide">
              Civic Observatory
              <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-mint-300" : "bg-coral-300"}`} aria-label={connected ? "Live connection" : "Connection offline"} />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-xl border border-mint-300/10 bg-ink-850 px-3 py-1.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">Day</span>
          <strong className="tabular text-lg text-mint-300">{status?.tick ?? "—"}</strong>
          <Badge tone={running ? "good" : status?.status === "halted" ? "bad" : "warn"}>{displayStatus}</Badge>
          <span title={inference.title}><Badge tone={inference.tone}>{inference.label}</Badge></span>
          {status?.active_tick != null && Number(status.active_tick) > Number(status?.tick ?? -1) && <Badge tone="warn">partial day {status.active_tick} · {status?.phase || status?.next_phase || "in progress"}</Badge>}
          {participantActive && <Badge tone="good">playing {participant?.controlled_agent?.name}</Badge>}
          {status?.acceptance_orchestration?.authorized && <Badge tone="warn">acceptance orchestrated</Badge>}
          {status?.target_tick != null && <Badge tone={limitReached ? "good" : "warn"}>{limitReached ? `target t${status.target_tick} reached` : `${status.remaining_ticks} days to t${status.target_tick}`}</Badge>}
          {status?.rate_limit && <Badge tone="warn">rate limited · retry {Math.ceil(status.rate_limit.cooldown_remaining_s)}s</Badge>}
          {hosted && !canControl && <Badge>observer · read only</Badge>}
        </div>

        <nav className="flex flex-wrap items-center gap-1.5" aria-label="Simulation controls">
          <button className="button button-primary" disabled={!canControl || loading || running || terminal || limitReached || busy || participantActive} onClick={() => action("start", "/api/run/start")}>▶ Run</button>
          <button className="button" disabled={!canControl || loading || running || terminal || limitReached || busy || (participantActive && !participantReady)} onClick={() => action("step", "/api/run/step")}>Step</button>
          <button className="button" disabled={!canControl || loading || pauseDisabled} onClick={() => action("pause", "/api/run/pause")}>Pause</button>
          <button className="button button-danger" disabled={!canControl || loading || stopDisabled} onClick={() => action("stop", "/api/run/stop")}>{hosted ? "Stop" : "Stop + report"}</button>
          <label className="sr-only" htmlFor="run-speed">Simulation speed</label>
          <select id="run-speed" className="field !w-auto !py-2" value={String(status?.speed_delay_s ?? 0)} disabled={!canControl || loading || terminal || busy} onChange={event => action("speed", "/api/run/speed", { delay_s: Number(event.target.value) })}>
            <option value="0">Max speed</option>
            <option value="0.25">0.25 s/day</option>
            <option value="1">1 s/day</option>
            <option value="3">3 s/day</option>
          </select>
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          {!hosted && <button className="button hidden sm:inline-flex" onClick={onReplay}>Replay viewer</button>}
          {!hosted && <button className="button" disabled={terminal} onClick={onShock}>Inject shock</button>}
          {!hosted && <button className="button hidden md:inline-flex" disabled={busy} onClick={() => action("report", "/api/report")}>Generate report</button>}
        </div>

        <div className="w-full min-w-[200px] sm:ml-auto sm:w-64">
          <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-slate-500">
            <span>Provider budget · L{status?.governor?.level ?? 0}</span>
            <span className="tabular">${number(spend, 2)} / {capped ? `$${number(cap, 0)}` : "uncapped"}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink-700" role="progressbar" aria-label={capped ? "Provider budget used" : "Provider spend uncapped"} aria-valuenow={fraction} aria-valuemin="0" aria-valuemax="100">
            <div className="h-full rounded-full bg-gradient-to-r from-mint-400 via-gold-300 to-coral-300 transition-[width]" style={{ width: `${fraction}%` }} />
          </div>
        </div>

        {!hosted && <CitizenMenu
          runId={status?.run_id}
          navigation={status?.navigation}
        />}
      </div>
    </header>
  );
}
