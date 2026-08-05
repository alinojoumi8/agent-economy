import { useCallback, useState } from "react";
import { hostedApi, hostedPost } from "../api.js";
import {
  configureHostedRouting,
  hostedCapabilities,
  isUuid,
  tenantApiPath,
} from "../hostedRouting.js";
import { Observatory } from "./Observatory";
import { AgentConnectionsPanel } from "./AgentConnectionsPanel";
import { Badge, Empty, Panel } from "./ui";

function errorMessage(reason) {
  return reason instanceof Error ? reason.message : String(reason);
}

function SessionBar({ session, selectedRun, onChooseRun, onLogout }) {
  return <div className="border-b border-mint-300/10 bg-ink-950/95 px-3 py-2 sm:px-5">
    <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-2 text-xs">
      <span className="eyebrow">Hosted tenant</span>
      <code className="text-slate-400">{session.tenant_id}</code>
      <Badge tone={session.role === "admin" ? "good" : "neutral"}>{session.role}</Badge>
      <span className="text-slate-600">user {session.user_id}</span>
      {selectedRun && <button className="button !min-h-8" onClick={onChooseRun}>Runs · {selectedRun.display_name}</button>}
      <button className="button ml-auto !min-h-8" onClick={onLogout}>Log out</button>
    </div>
  </div>;
}

function HostedAccess({ config, onAuthenticated }) {
  const [view, setView] = useState("login");
  const [tenantId, setTenantId] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function login(event) {
    event.preventDefault();
    if (!isUuid(tenantId)) {
      setError("Enter the tenant UUID supplied by your administrator.");
      return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await hostedPost("/auth/login", {
        tenant_id: tenantId, email: email.trim(), password,
      });
      configureHostedRouting({
        tenantId: result.tenant_id,
        csrfCookieName: config.csrf_cookie_name,
        csrfHeaderName: config.csrf_header_name,
      });
      const verified = await hostedApi(tenantApiPath("/session", result.tenant_id));
      onAuthenticated({ ...verified, email: email.trim() });
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  async function register(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await hostedPost("/auth/register", {
        invite_token: inviteToken.trim(), email: email.trim(),
        display_name: displayName.trim(), password,
      });
      setTenantId(result.tenant_id);
      setInviteToken("");
      setDisplayName("");
      setNotice("Registration complete. Sign in with the tenant UUID shown below.");
      setView("login");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return <main className="mx-auto flex min-h-screen max-w-6xl items-center px-4 py-10">
    <div className="grid w-full gap-4 lg:grid-cols-[1fr_460px]">
      <section className="rounded-2xl border border-mint-300/15 bg-ink-900/80 p-7">
        <div className="eyebrow">Agent Economy · Hosted</div>
        <h1 className="mt-3 max-w-xl text-4xl font-semibold text-slate-100">One deterministic world per tenant run.</h1>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400">Sessions stay in secure HttpOnly cookies. Tenant and run selection remain in this browser tab only; credentials are never placed in browser storage.</p>
        <div className="mt-8 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-mint-300/10 bg-ink-950/45 p-4"><div className="eyebrow">Isolation</div><p className="mt-2 text-xs text-slate-500">Tenant-scoped catalog, run, and artifact boundaries.</p></div>
          <div className="rounded-xl border border-mint-300/10 bg-ink-950/45 p-4"><div className="eyebrow">Roles</div><p className="mt-2 text-xs text-slate-500">Agent owners manage their connectors; administrators operate runs.</p></div>
          <div className="rounded-xl border border-mint-300/10 bg-ink-950/45 p-4"><div className="eyebrow">Evidence</div><p className="mt-2 text-xs text-slate-500">Immutable snapshots at completed boundaries.</p></div>
        </div>
      </section>

      <section className="rounded-2xl border border-mint-300/15 bg-ink-850 p-6">
        <div className="mb-5 flex gap-2" role="group" aria-label="Hosted access">
          <button className={`button ${view === "login" ? "button-primary" : ""}`} onClick={() => setView("login")}>Sign in</button>
          <button className={`button ${view === "register" ? "button-primary" : ""}`} onClick={() => setView("register")}>Use invite</button>
        </div>
        {notice && <p role="status" className="mb-4 rounded-lg border border-mint-300/20 bg-mint-300/[.05] p-3 text-xs text-mint-300">{notice}</p>}
        {error && <p role="alert" className="mb-4 rounded-lg border border-coral-300/20 bg-coral-300/[.05] p-3 text-xs text-coral-300">{error}</p>}
        {view === "login" ? <form className="space-y-4" onSubmit={login}>
          <label className="block text-xs text-slate-400">Tenant UUID<input className="field mt-1" required value={tenantId} onChange={event => setTenantId(event.target.value)} autoComplete="organization" /></label>
          <label className="block text-xs text-slate-400">Email<input className="field mt-1" type="email" required value={email} onChange={event => setEmail(event.target.value)} autoComplete="username" /></label>
          <label className="block text-xs text-slate-400">Password<input className="field mt-1" type="password" required value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" /></label>
          <button className="button button-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form> : <form className="space-y-4" onSubmit={register}>
          <label className="block text-xs text-slate-400">One-time invite token<input className="field mt-1" required value={inviteToken} onChange={event => setInviteToken(event.target.value)} autoComplete="off" /></label>
          <label className="block text-xs text-slate-400">Email<input className="field mt-1" type="email" required value={email} onChange={event => setEmail(event.target.value)} autoComplete="username" /></label>
          <label className="block text-xs text-slate-400">Display name<input className="field mt-1" required value={displayName} onChange={event => setDisplayName(event.target.value)} autoComplete="name" /></label>
          <label className="block text-xs text-slate-400">New password<input className="field mt-1" type="password" minLength={12} required value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password" /></label>
          <button className="button button-primary w-full" disabled={busy}>{busy ? "Registering…" : "Register"}</button>
        </form>}
      </section>
    </div>
  </main>;
}

function RunDirectory({ config, session, runs, members, busy, error, onRefresh, onSelect, onCreated, onMembersChanged }) {
  const capabilities = hostedCapabilities(session.role);
  const [displayName, setDisplayName] = useState("");
  const [profile, setProfile] = useState(config.profiles[0] || "");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("observer");
  const [oneTimeInvite, setOneTimeInvite] = useState(null);
  const [memberDrafts, setMemberDrafts] = useState({});
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  async function perform(action) {
    setActionBusy(true); setActionError("");
    try { return await action(); }
    catch (reason) { setActionError(errorMessage(reason)); return null; }
    finally { setActionBusy(false); }
  }

  async function createRun(event) {
    event.preventDefault();
    await perform(async () => {
      const value = await hostedPost(tenantApiPath("/runs"), {
        profile_slug: profile, display_name: displayName.trim(),
      });
      setDisplayName("");
      await onCreated(value.run_id);
    });
  }

  async function createInvite(event) {
    event.preventDefault();
    await perform(async () => {
      const value = await hostedPost(tenantApiPath("/invitations"), {
        email: inviteEmail.trim(), role: inviteRole,
      });
      setInviteEmail("");
      setOneTimeInvite(value);
    });
  }

  async function revokeInvite() {
    if (!oneTimeInvite?.invite_token) return;
    await perform(async () => {
      await hostedPost(tenantApiPath("/invitations/revoke"), {
        invite_token: oneTimeInvite.invite_token,
      });
      setOneTimeInvite(null);
    });
  }

  async function updateMember(member) {
    const draft = memberDrafts[member.user_id] || member;
    await perform(async () => {
      await hostedApi(tenantApiPath(`/members/${member.user_id}`), {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        routingBody: { role: draft.role, enabled: draft.status !== "revoked" },
        body: JSON.stringify({ role: draft.role, enabled: draft.status !== "revoked" }),
      });
      await onMembersChanged();
    });
  }

  return <main className="mx-auto grid max-w-[1500px] grid-cols-12 gap-4 px-4 py-6">
    <div className="col-span-full flex flex-wrap items-end justify-between gap-3">
      <div><div className="eyebrow">Tenant workspace</div><h1 className="mt-1 text-2xl font-semibold text-slate-100">Choose a simulation run</h1><p className="mt-1 text-xs text-slate-500">Only runs returned by this tenant-scoped session are selectable.</p></div>
      <button className="button" disabled={busy} onClick={onRefresh}>Refresh</button>
    </div>
    {error && <div role="alert" className="col-span-full rounded-xl border border-coral-300/20 bg-coral-300/[.05] p-3 text-xs text-coral-300">{error}</div>}
    {actionError && <div role="alert" className="col-span-full rounded-xl border border-coral-300/20 bg-coral-300/[.05] p-3 text-xs text-coral-300">{actionError}</div>}

    <Panel title={`Runs · ${runs.length}`} eyebrow="Tenant-scoped catalog" className="col-span-full lg:col-span-8">
      <div className="scrollbar max-h-[520px] overflow-y-auto p-4">
        {runs.length ? <div className="space-y-2">{runs.map(run => <button key={run.run_id} className="flex w-full items-center justify-between gap-3 rounded-xl border border-mint-300/10 bg-ink-950/35 p-4 text-left hover:border-mint-300/30" onClick={() => onSelect(run)}>
          <div><strong className="text-sm text-slate-200">{run.display_name}</strong><p className="mt-1 text-[10px] text-slate-600">{run.run_id} · {run.run_key}</p></div><Badge tone={run.status === "running" ? "good" : run.status === "failed" ? "bad" : "neutral"}>{run.status}</Badge>
        </button>)}</div> : <Empty>No runs exist for this tenant yet.</Empty>}
      </div>
    </Panel>

    <div className="col-span-full space-y-4 lg:col-span-4">
      {capabilities.createRuns ? <Panel title="Create run" eyebrow="Administrator">
        <form className="space-y-3 p-4" onSubmit={createRun}>
          <label className="block text-xs text-slate-500">Display name<input className="field mt-1" maxLength={160} required value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>
          <label className="block text-xs text-slate-500">Allowlisted profile<select className="field mt-1" required value={profile} onChange={event => setProfile(event.target.value)}>{config.profiles.map(slug => <option key={slug}>{slug}</option>)}</select></label>
          <button className="button button-primary w-full" disabled={busy || actionBusy || !profile}>Create paused run</button>
        </form>
      </Panel> : <Panel title="Observer access" eyebrow="Read only"><p className="p-4 text-xs leading-relaxed text-slate-500">You can inspect and follow tenant runs. Creation and controls require an administrator.</p></Panel>}

      {capabilities.administerTenant && <Panel title="Invite member" eyebrow="One-time credential">
        <form className="space-y-3 p-4" onSubmit={createInvite}>
          <label className="block text-xs text-slate-500">Email<input className="field mt-1" type="email" required value={inviteEmail} onChange={event => setInviteEmail(event.target.value)} /></label>
          <label className="block text-xs text-slate-500">Role<select className="field mt-1" value={inviteRole} onChange={event => setInviteRole(event.target.value)}><option value="observer">Observer</option><option value="agent_owner">Agent owner</option><option value="admin">Administrator</option></select></label>
          <button className="button w-full" disabled={busy || actionBusy}>Create invite</button>
        </form>
        {oneTimeInvite && <div className="border-t border-mint-300/10 p-4"><div className="eyebrow">Copy now · shown once</div><code className="mt-2 block break-all rounded-lg bg-ink-950 p-3 text-xs text-mint-300">{oneTimeInvite.invite_token}</code><button className="button mt-2" disabled={actionBusy} onClick={revokeInvite}>Revoke invite</button></div>}
      </Panel>}
    </div>

    {capabilities.administerTenant && <Panel title={`Members · ${members.length}`} eyebrow="Role and session controls" className="col-span-full">
      <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>User UUID</th><th>Role</th><th>Status</th><th /></tr></thead><tbody>{members.map(member => {
        const draft = memberDrafts[member.user_id] || member;
        const self = member.user_id === session.user_id;
        return <tr key={member.user_id}><td><code className="text-[10px]">{member.user_id}</code>{self && <Badge tone="good">you</Badge>}</td><td><select className="field !w-auto !py-1.5" disabled={self} value={draft.role} onChange={event => setMemberDrafts(current => ({ ...current, [member.user_id]: { ...draft, role: event.target.value } }))}><option value="observer">Observer</option><option value="agent_owner">Agent owner</option><option value="admin">Admin</option></select></td><td><select className="field !w-auto !py-1.5" disabled={self} value={draft.status} onChange={event => setMemberDrafts(current => ({ ...current, [member.user_id]: { ...draft, status: event.target.value } }))}><option value="active">Active</option><option value="revoked">Revoked</option></select></td><td><button className="button !min-h-8" disabled={self || busy || actionBusy} onClick={() => updateMember(member)}>Save</button></td></tr>;
      })}</tbody></table></div>
    </Panel>}
  </main>;
}

export function HostedShell({ config }) {
  const [session, setSession] = useState(null);
  const [runs, setRuns] = useState([]);
  const [members, setMembers] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [directoryOpen, setDirectoryOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (session) {
    configureHostedRouting({
      tenantId: session.tenant_id,
      runId: selectedRun?.run_id || null,
      csrfCookieName: config.csrf_cookie_name,
      csrfHeaderName: config.csrf_header_name,
    });
  }

  const refreshDirectory = useCallback(async (current = session) => {
    if (!current) return;
    setBusy(true); setError("");
    try {
      const runResult = await hostedApi(tenantApiPath("/runs", current.tenant_id));
      const safeRuns = (runResult.runs || []).filter(run => run.tenant_id === current.tenant_id && isUuid(run.run_id));
      setRuns(safeRuns);
      if (current.role === "admin") {
        const memberResult = await hostedApi(tenantApiPath("/members", current.tenant_id));
        setMembers((memberResult.members || []).filter(member => member.tenant_id === current.tenant_id));
      } else {
        setMembers([]);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally { setBusy(false); }
  }, [session]);

  async function authenticated(value) {
    setSession(value); setSelectedRun(null); setDirectoryOpen(true);
    await refreshDirectory(value);
  }

  async function logout() {
    setBusy(true); setError("");
    try { await hostedPost("/auth/logout"); }
    catch (reason) { setError(errorMessage(reason)); }
    finally {
      configureHostedRouting({
        csrfCookieName: config.csrf_cookie_name,
        csrfHeaderName: config.csrf_header_name,
      });
      setSession(null); setRuns([]); setMembers([]); setSelectedRun(null);
      setBusy(false);
    }
  }

  async function created(runId) {
    await refreshDirectory();
    const result = await hostedApi(tenantApiPath(`/runs/${runId}`));
    if (result.tenant_id === session.tenant_id) {
      setSelectedRun(result); setDirectoryOpen(false);
    }
  }

  if (!session) return <HostedAccess config={config} onAuthenticated={authenticated} />;
  return <div className="min-h-screen">
    <SessionBar session={session} selectedRun={selectedRun} onChooseRun={() => setDirectoryOpen(true)} onLogout={logout} />
    {directoryOpen || !selectedRun ? <RunDirectory config={config} session={session} runs={runs} members={members} busy={busy} error={error}
      onRefresh={() => refreshDirectory()} onSelect={run => { setSelectedRun(run); setDirectoryOpen(false); }}
      onCreated={created} onMembersChanged={() => refreshDirectory()} />
      : <>
        {(session.role === "agent_owner" || session.role === "admin") && <AgentConnectionsPanel session={session} run={selectedRun} />}
        <Observatory key={selectedRun.run_id} hostedSession={{ ...session, run: selectedRun }} />
      </>}
  </div>;
}
