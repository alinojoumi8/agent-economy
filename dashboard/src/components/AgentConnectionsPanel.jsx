import { useCallback, useEffect, useState } from "react";
import { hostedApi, hostedPost } from "../api.js";
import { connectionActivity, createConnectionPayload, scopesForTier } from "../agentConnections.js";
import { tenantApiPath } from "../hostedRouting.js";
import { Badge, Empty, Panel } from "./ui";

const freshDraft = () => ({
  displayName: "", biography: "", occupation: "", tier: "actor",
  wakeInterval: 1,
});

function message(reason) {
  return reason instanceof Error ? reason.message : String(reason);
}

export function AgentConnectionsPanel({ session, run }) {
  const [connections, setConnections] = useState([]);
  const [draft, setDraft] = useState(freshDraft);
  const [credential, setCredential] = useState(null);
  const [quota, setQuota] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const result = await hostedApi(tenantApiPath("/agent-connections", session.tenant_id));
      setConnections((result.connections || []).filter(item => item.run_id === run.run_id));
      if (session.role === "admin") {
        const policy = await hostedApi(tenantApiPath("/agent-policy", session.tenant_id));
        setQuota(Number(policy.max_external_agents_per_run));
      }
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }, [run.run_id, session.tenant_id]);

  useEffect(() => { refresh(); }, [refresh]);

  async function create(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setCredential(null);
    try {
      const result = await hostedPost(
        tenantApiPath("/agent-connections", session.tenant_id),
        createConnectionPayload(run.run_id, draft));
      setCredential(result.credential);
      setNotice("Connection created. Copy the credential now; it will not be shown again.");
      setDraft(freshDraft());
      await refresh();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function credentials(connection, action) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await hostedPost(
        tenantApiPath(`/agent-connections/${connection.id}/credentials`, session.tenant_id),
        { action });
      if (action === "rotate") {
        setCredential(result);
        setNotice("Credential rotated. Copy the replacement now; the prior token is revoked.");
      } else {
        setCredential(null); setNotice("All active credentials were revoked.");
      }
      await refresh();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function status(connection, nextStatus) {
    setBusy(true); setError(""); setNotice("");
    try {
      await hostedApi(
        tenantApiPath(`/agent-connections/${connection.id}`, session.tenant_id), {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          routingBody: { status: nextStatus }, body: JSON.stringify({ status: nextStatus }),
        });
      setNotice(`Connection ${nextStatus}.`); await refresh();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function saveQuota(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const policy = await hostedApi(tenantApiPath("/agent-policy", session.tenant_id), {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        routingBody: { max_external_agents_per_run: Number(quota) },
        body: JSON.stringify({ max_external_agents_per_run: Number(quota) }),
      });
      setQuota(Number(policy.max_external_agents_per_run));
      setNotice("Tenant external-agent quota updated.");
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function copyCredential() {
    if (!credential?.token) return;
    try { await navigator.clipboard.writeText(credential.token); setNotice("Credential copied."); }
    catch { setError("Clipboard access failed. Select and copy the credential manually."); }
  }

  return <section className="mx-auto max-w-[1800px] px-3 pt-4 sm:px-5" aria-label="External agent connections">
    {error && <p role="alert" className="mb-3 rounded-lg border border-coral-300/20 bg-coral-300/[.05] p-3 text-xs text-coral-300">{error}</p>}
    {notice && <p role="status" className="mb-3 rounded-lg border border-mint-300/20 bg-mint-300/[.05] p-3 text-xs text-mint-300">{notice}</p>}
    {credential?.token && <div className="mb-4 rounded-xl border border-gold-300/25 bg-gold-300/[.05] p-4">
      <div className="eyebrow">One-time personal agent token · copy now</div>
      <code className="mt-2 block break-all rounded-lg bg-ink-950 p-3 text-xs text-gold-300">{credential.token}</code>
      <div className="mt-2 flex gap-2"><button className="button" onClick={copyCredential}>Copy token</button><button className="button" onClick={() => setCredential(null)}>I saved it</button></div>
    </div>}
    <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
      <Panel title="Connect an outside agent" eyebrow="Hermes · OpenClaw · custom MCP or REST">
        <form className="space-y-3 p-4" onSubmit={create}>
          <label className="block text-xs text-slate-500">Public name<input className="field mt-1" maxLength={80} required value={draft.displayName} onChange={event => setDraft(current => ({ ...current, displayName: event.target.value }))} /></label>
          <label className="block text-xs text-slate-500">Permission tier<select className="field mt-1" value={draft.tier} onChange={event => setDraft(current => ({ ...current, tier: event.target.value }))}><option value="observer">Observer</option><option value="commons">Commons</option><option value="actor">World actor</option></select></label>
          <p className="text-[11px] text-slate-600">Scopes: {scopesForTier(draft.tier).join(", ")}</p>
          <label className="block text-xs text-slate-500">Biography<textarea className="field mt-1" maxLength={500} value={draft.biography} onChange={event => setDraft(current => ({ ...current, biography: event.target.value }))} /></label>
          {draft.tier !== "observer" && <label className="block text-xs text-slate-500">Preferred occupation<input className="field mt-1" maxLength={80} value={draft.occupation} onChange={event => setDraft(current => ({ ...current, occupation: event.target.value }))} /></label>}
          <label className="block text-xs text-slate-500">Wake interval (ticks)<input className="field mt-1" type="number" min="1" max="365" value={draft.wakeInterval} onChange={event => setDraft(current => ({ ...current, wakeInterval: event.target.value }))} /></label>
          <button className="button button-primary w-full" disabled={busy}>Create dedicated connection</button>
          <p className="text-[11px] leading-relaxed text-slate-600">Commons and actor tiers create a new citizen at the next deterministic arrival boundary. They never take over an existing citizen.</p>
        </form>
        {session.role === "admin" && <form className="border-t border-mint-300/10 p-4" onSubmit={saveQuota}>
          <label className="block text-xs text-slate-500">Maximum connections per run<input className="field mt-1" type="number" min="0" max="10000" value={quota} onChange={event => setQuota(event.target.value)} /></label>
          <button className="button mt-2 w-full" disabled={busy}>Save tenant quota</button>
        </form>}
      </Panel>
      <Panel title={`Connections · ${connections.length}`} eyebrow={`Run ${run.display_name}`} action={<button className="button !min-h-8" disabled={busy} onClick={refresh}>Refresh</button>}>
        {connections.length ? <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>Agent</th><th>Tier and scopes</th><th>Actor</th><th>Last seen / lease</th><th>Controls</th></tr></thead><tbody>{connections.map(connection => <tr key={connection.id}>
          <td><strong>{connection.display_name}</strong><br /><code className="text-[10px]">{connection.id}</code></td>
          <td><Badge tone={connection.tier === "actor" ? "good" : "neutral"}>{connection.tier}</Badge><div className="mt-1 text-[10px] text-slate-600">{(connection.scopes || []).join(", ")}</div></td>
          <td>{connection.actor_id ? `Citizen ${connection.actor_id}` : "Pending"}<div className="mt-1"><Badge tone={connectionActivity(connection) === "online" ? "good" : connection.status === "revoked" ? "bad" : "warn"}>{connectionActivity(connection)}</Badge></div></td>
          <td className="text-[10px] text-slate-500">{connection.last_seen_at || "Never"}<br />{connection.lease_expires_at ? `lease ${connection.lease_expires_at}` : "no active lease"}</td>
          <td><div className="flex flex-wrap gap-1"><button className="button !min-h-8" disabled={busy || connection.status === "revoked"} onClick={() => credentials(connection, "rotate")}>Rotate</button><button className="button !min-h-8" disabled={busy || connection.status === "revoked"} onClick={() => credentials(connection, "revoke")}>Revoke token</button>{session.role === "admin" && connection.status !== "revoked" && <button className="button !min-h-8" disabled={busy} onClick={() => status(connection, connection.status === "suspended" ? "active" : "suspended")}>{connection.status === "suspended" ? "Resume" : "Suspend"}</button>}</div></td>
        </tr>)}</tbody></table></div> : <Empty>No external agents are attached to this run.</Empty>}
      </Panel>
    </div>
  </section>;
}
