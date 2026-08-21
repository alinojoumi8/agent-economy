import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildPulseSignals,
  buildPulseTimeline,
  ledgerInvariantState,
  normalizePulseWorld,
  pulseViewMode,
} from "../src/workspaces/worldPulseModel.js";
const pulseSource = readFileSync(
  new URL("../src/workspaces/WorldPulseWorkspace.tsx", import.meta.url),
  "utf8",
);
const shellSource = readFileSync(
  new URL("../src/app/WorkspaceShell.tsx", import.meta.url),
  "utf8",
);

test("pulse signals rank committed salience without exposing event payloads", () => {
  const signals = buildPulseSignals([
    {
      id: 11,
      tick: 8,
      phase: "MARKET",
      kind: "goods_sale",
      subject_type: "firm",
      subject_id: 4,
      importance: 1.2,
      payload: { private_body: "PRIVACY-CANARY-world-pulse" },
    },
    {
      id: 12,
      tick: 9,
      phase: "FINALIZE",
      kind: "firm_bankrupt",
      subject_type: "firm",
      subject_id: 7,
      importance: 3.5,
      payload: { secret_url: "https://private.invalid/canary" },
    },
  ]);

  assert.equal(signals[0].eventId, 12);
  assert.equal(signals[0].tone, "critical");
  assert.equal(signals[0].evidenceRef, "EV-12");
  assert.match(signals[0].summary, /Firm #7/);
  assert.doesNotMatch(JSON.stringify(signals), /PRIVACY-CANARY|private\.invalid|payload/);
});

test("pulse signals use an honest generic fallback when no committed event exists", () => {
  const [fallback] = buildPulseSignals([]);

  assert.equal(fallback.eventId, null);
  assert.equal(fallback.headline, "No committed change at this cursor");
  assert.match(fallback.why, /Nothing is inferred/);
  assert.equal(fallback.evidenceRef, null);
});

test("pulse signals never turn absent identifiers into zero-valued evidence", () => {
  const [signal] = buildPulseSignals([{
    id: null,
    tick: "",
    subject_id: " ",
    kind: "policy_change",
  }]);

  assert.equal(signal.eventId, null);
  assert.equal(signal.tick, null);
  assert.equal(signal.evidenceRef, null);
  assert.doesNotMatch(signal.summary, /#0|tick 0/);
});

test("pulse world uses projected region coordinates and historical agent membership", () => {
  const world = normalizePulseWorld({
    enabled: true,
    regions: [
      { id: 2, name: "Harbor Ward", x: 0.25, y: 0.7 },
      { id: 3, name: "Civic Forum", x: 80, y: 10 },
    ],
    agents: [
      { id: 1, region_id: 2 },
      { id: 2, region_id: 2 },
      { id: 3, region_id: 3 },
    ],
    organizations: [{ id: 9, active: true }],
    summary: { trade_count: 4, migration_count: 1 },
  });

  assert.deepEqual(
    world.regions.map(region => [region.id, region.population, region.x, region.y]),
    [[2, 2, 25, 70], [3, 1, 80, 10]],
  );
  assert.equal(world.population, 3);
  assert.equal(world.activeOrganizations, 1);
  assert.equal(world.tradeCount, 4);
});

test("pulse world omits invalid region identities and never invents coordinates", () => {
  const world = normalizePulseWorld({
    regions: [
      { id: 2, name: "Harbor Ward", x: null, y: "" },
      { id: null, name: "Fabricated zero", x: 0.4, y: 0.5 },
      { id: "bad", name: "Invalid link", x: 30, y: 40 },
    ],
    agents: [{ id: 1, region_id: null }, { id: 2, region_id: 2 }],
  });

  assert.deepEqual(world.regions.map(region => region.id), [2]);
  assert.equal(world.regions[0].population, 1);
  assert.equal(world.regions[0].x, null);
  assert.equal(world.regions[0].y, null);
});

test("pulse timeline links only strict committed event identities", () => {
  const timeline = buildPulseTimeline([
    { id: null, tick: 0, kind: "policy_change", importance: 5 },
    { id: 8, tick: "", kind: "firm_bankrupt", importance: 4 },
    { id: "9", tick: "12", kind: "goods_sale", importance: 1.2 },
  ]);

  assert.deepEqual(timeline, [{
    eventId: 9,
    tick: 12,
    kind: "Goods sale",
    importance: 1.2,
  }]);
});

test("pulse view mode keeps historical cursors visibly distinct from live state", () => {
  assert.deepEqual(pulseViewMode("live", 183), {
    historical: false,
    eyebrow: "Live observer briefing",
    cursor: "Tick 183",
  });
  assert.deepEqual(pulseViewMode("160", 160), {
    historical: true,
    eyebrow: "Historical observer briefing",
    cursor: "Tick 160",
  });

});

test("ledger invariant never reports balance without projected evidence", () => {
  assert.deepEqual(ledgerInvariantState(undefined), { state: "unreported", balance: null });
  assert.deepEqual(ledgerInvariantState(Number.NaN), { state: "unreported", balance: null });
  assert.deepEqual(ledgerInvariantState(0), { state: "balanced", balance: 0 });
  assert.deepEqual(ledgerInvariantState(17), { state: "exceptional", balance: 17 });
});
test("World Pulse keeps one observer-safe projection path and five primary destinations", () => {
  assert.match(pulseSource, /"workspace\.world",\s*"\/api\/v2\/workspaces\/world"/);
  assert.match(pulseSource, /params\.set\("domains", "summary,alerts,events"\)/);
  assert.match(pulseSource, /enabled: live/);
  assert.match(pulseSource, /Historical context · read-only/);
  assert.match(pulseSource, /hasAuthoritativeRunStatus/);
  assert.match(pulseSource, /controlsUnavailable/);
  assert.doesNotMatch(pulseSource, /world-pulse-map" role="img"/);
  assert.doesNotMatch(pulseSource, /api\/llm\/runtime/);
  assert.doesNotMatch(pulseSource, /\.payload\b/);
  assert.match(shellSource, /const primaryRouteGroups = routeGroups\.slice\(0, 1\)/);
  for (const route of [
    ["overview", "Pulse"], ["live-city", "City"], ["people", "People"],
    ["commons", "Commons"], ["investigations", "Evidence Lab"],
  ]) {
    assert.match(shellSource, new RegExp(`path: "${route[0]}", label: "${route[1]}"`));
  }
});
