import assert from "node:assert/strict";
import test from "node:test";
import { parseObserverViewState, patchObserverViewState } from "../src/app/observerViewStateCore.js";
import { cityEvidenceParams, cityWorkspaceHref } from "../src/app/cityNavigation.js";
import { citySociety, householdForPerson, childNeedsByCurrency } from "../src/lib/citySociety.js";

test("household and typed institution bookmarks survive navigation and remain exclusive", () => {
  for (const selection of [{ household: 7 }, { institution: "bank:3" }]) {
    const params = patchObserverViewState(new URLSearchParams("agent=1&follow=1&tick=2&fork=child&camera=40,60,4"), selection);
    const state = parseObserverViewState(params);
    assert.equal(state.agent, null); assert.equal(state.follow, null);
    const href = cityWorkspaceHref("run", parseObserverViewState(cityEvidenceParams(state)));
    assert.deepEqual(parseObserverViewState(new URL(href, "http://local").searchParams), state);
    for (const patch of [{ agent: 2 }, { firm: 2 }, { place: 2 }, { project: "site:2" }]) {
      const changed = parseObserverViewState(patchObserverViewState(params, patch));
      assert.equal(changed.household, null); assert.equal(changed.institution, null);
    }
    const other = parseObserverViewState(patchObserverViewState(params,
      selection.household ? { institution: "bank:2" } : { household: 2 }));
    assert.equal(selection.household ? other.household : other.institution, null);
  }
  for (const value of ["bank:0", "bank:-1", "bank:1.2", "bank:9007199254740993", "school:1", "bank:1:2"]) {
    assert.equal(parseObserverViewState(new URLSearchParams({ institution: value })).institution, null);
  }
  for (const value of ["0", "-1", "1.2", "9007199254740993", "private"]) {
    assert.equal(parseObserverViewState(new URLSearchParams({ household: value })).household, null);
  }
  const conflict = parseObserverViewState(new URLSearchParams("institution=bank:2&household=3&project=4&firm=5&agent=6&follow=6&place=7"));
  assert.equal(conflict.institution, "bank:2");
  for (const key of ["household", "project", "firm", "agent", "follow", "place"]) assert.equal(conflict[key], null);
});

test("society records require the map tick, declared source and visibility", () => {
  const households = { available: true, tick: 2, source: "recorded_household_membership",
    visibility: "core_members_only", items: [{ id: 7, name: "Household #7", child_needs: [], members: [
      { agent_id: 1, name: "Parent", age_years: 30, joined_tick: 0, legacy_dependents: 0,
        age_band: "adult", role: "adult", guardian_agent_id: null }] }] };
  assert.equal(householdForPerson(citySociety({ households }, 2).households, 1).id, 7);
  assert.equal(householdForPerson(citySociety({ households }, 1).households, 1), null);
  for (const patch of [{ source: "live" }, { visibility: "private" }, { available: null }, { items: null },
    { items: [null] }, { items: [{ id: 7 }] }, { items: [...households.items, ...households.items] },
    { items: [{ ...households.items[0], child_needs: [{ child_agent_id: 1, spent_cents: "90" }] }] }]) {
    assert.equal(citySociety({ households: { ...households, ...patch } }, 2).households.available, false);
  }
  assert.equal(citySociety(null, 2).institutions.available, false);
});

test("child purchase totals retain currency boundaries and missing records", () => {
  assert.deepEqual(childNeedsByCurrency([]), []);
  assert.deepEqual(childNeedsByCurrency([{ currency_code: "USD", spent_cents: 0 },
    { currency_code: "CAD", spent_cents: 40 }, { currency_code: "USD", spent_cents: 30 }]),
  [["CAD", 40], ["USD", 30]]);
});
