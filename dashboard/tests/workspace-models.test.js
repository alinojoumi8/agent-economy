import assert from "node:assert/strict";
import test from "node:test";

import {
  agentViewState,
  flattenThreadPages,
  nextThreadPageParam,
  routedThreadLookup,
} from "../src/workspaces/newsCommunicationsModel.js";
import {
  defaultRootEventId,
  resolveCausalRoot,
  rootEventSearch,
  validSelection,
} from "../src/workspaces/investigationsWorkspaceModel.js";
import {
  agentPageForSelection,
  featuredAgentId,
  resolveSelectedAgentId,
  projectInvolvesAgent,
} from "../src/workspaces/peopleWorkspaceModel.js";

test("a shared property's beneficiaries and guardian can follow it without changing its original owner", () => {
  const property = { kind: "construction", status: "active", owner_agent_id: null,
    beneficial_owner_ids: [2, 3], steward_agent_id: 4, original_owner_agent_id: 1 };
  assert.equal(projectInvolvesAgent(property, 2), true);
  assert.equal(projectInvolvesAgent(property, 3), true);
  assert.equal(projectInvolvesAgent(property, 4), true);
  assert.equal(projectInvolvesAgent(property, 1), false);
  assert.equal(projectInvolvesAgent(property, null), false);
  assert.equal(featuredAgentId([{ id: 2 }, { id: 4 }], [property]), 4);
});
import { MARKET_WINDOW, normalizeMarketsWorkspace } from "../src/workspaces/marketsWorkspaceModel.js";

test("agent view is only active with a positive agent id", () => {
  assert.equal(agentViewState("ordinary", "12").active, false);
  assert.deepEqual(agentViewState("agent", ""), {
    inputValue: "", agentId: null, active: false, awaitingAgentId: true, ready: false,
  });
  assert.equal(agentViewState("agent", "0").awaitingAgentId, true);
  assert.deepEqual(agentViewState("agent", "1a2"), {
    inputValue: "12", agentId: "12", active: true, awaitingAgentId: false, ready: true,
  });
});

test("thread pages follow the server cursor and deep links resolve beyond the loaded page", () => {
  assert.equal(nextThreadPageParam({ truncated: false, next_after_thread_id: 50 }), undefined);
  assert.equal(nextThreadPageParam({ truncated: true, next_after_thread_id: 50 }), 50);
  assert.equal(nextThreadPageParam({ truncated: true, next_after_thread_id: null }), undefined);
  const threads = flattenThreadPages([
    { items: [{ thread_id: 1 }, { thread_id: 2 }] },
    { items: [{ thread_id: 2 }, { thread_id: 3 }] },
  ]);
  assert.deepEqual(threads.map(item => item.thread_id), [1, 2, 3]);
  assert.deepEqual(routedThreadLookup("2", threads), { threadId: 2, loaded: true, after: null });
  assert.deepEqual(routedThreadLookup("73", threads), { threadId: 73, loaded: false, after: 72 });
  assert.deepEqual(routedThreadLookup(undefined, threads), { threadId: null, loaded: false, after: null });
});

test("the default causal root is the newest committed event and typed roots win", () => {
  assert.equal(defaultRootEventId([{ id: 40, kind: "goods_sale" }, { id: 41, kind: "payroll" }]), 40);
  assert.equal(defaultRootEventId([{ id: 41, kind: "payroll" }]), 41);
  assert.equal(defaultRootEventId([]), null);
  assert.deepEqual(resolveCausalRoot(new URLSearchParams("kind=commons_entry&id=1"), 40),
    { kind: "commons_entry", id: 1, source: "reference" });
  assert.deepEqual(resolveCausalRoot(new URLSearchParams("kind=commons_entry"), 40),
    { kind: "event", id: 40, source: "recent" });
  assert.deepEqual(resolveCausalRoot(new URLSearchParams("event=7"), 40),
    { kind: "event", id: 7, source: "event" });
  assert.deepEqual(resolveCausalRoot(new URLSearchParams(""), null),
    { kind: "event", id: 0, source: "none" });
  const next = rootEventSearch(new URLSearchParams("kind=commons_entry&id=1&tick=4"), "9x");
  assert.equal(next.toString(), "tick=4&event=9");
  assert.equal(validSelection({ kind: "event", id: 41 }, [{ kind: "event", id: 41 }]).id, 41);
  assert.equal(validSelection({ kind: "event", id: 41 }, [{ kind: "event", id: 9 }]), null);
});

test("people selection is pinned against polling and pages only on selection change", () => {
  const agents = [{ id: 4, runtime: null }, { id: 9, runtime: { state: "thinking" } }];
  assert.equal(featuredAgentId(agents, []), 9);
  assert.equal(resolveSelectedAgentId({ requestedId: 4, pinnedId: 9, featuredId: 9, agents }), 4);
  assert.equal(resolveSelectedAgentId({ requestedId: null, pinnedId: 4, featuredId: 9, agents }), 4);
  assert.equal(resolveSelectedAgentId({ requestedId: null, pinnedId: 77, featuredId: 9, agents }), 9);
  const visible = Array.from({ length: 80 }, (_, index) => ({ id: index + 1 }));
  assert.equal(agentPageForSelection({ selectedId: 50, visibleAgents: visible, pageSize: 36, pagedFor: null }), 1);
  assert.equal(agentPageForSelection({ selectedId: 50, visibleAgents: visible, pageSize: 36, pagedFor: 50 }), null);
  assert.equal(agentPageForSelection({ selectedId: 999, visibleAgents: visible, pageSize: 36, pagedFor: null }), null);
});

test("market totals flag a full projection window", () => {
  const trades = Array.from({ length: MARKET_WINDOW }, (_, index) => ({ id: index + 1, tick: 1, qty: 2 }));
  const full = normalizeMarketsWorkspace({ trades });
  assert.equal(full.totals.tradeCount, MARKET_WINDOW);
  assert.equal(full.totals.windowed, true);
  assert.equal(normalizeMarketsWorkspace({ trades: trades.slice(0, 3) }).totals.windowed, false);
});
