import assert from "node:assert/strict";
import test from "node:test";
import { cityObjectRows, cityObjectPage } from "../src/lib/cityObjectList.js";
import { parseObserverViewState } from "../src/app/observerViewStateCore.js";
import { cityEvidenceParams, cityWorkspaceHref } from "../src/app/cityNavigation.js";

test("city list uses public records and filters all supported object kinds", () => {
  const model = { firms: [{ id: 3, name: "Shop" }], places: [], constructionProjects: [{ id: "site:4", name: "Clinic" }] };
  const society = { households: { available: true, items: [{ id: 7, name: "Household #7" }] },
    institutions: { available: true, items: [{ id: "bank:2", name: "Community Bank" }] } };
  const agents = [{ id: 1, name: "Parent", role: "citizen" }];
  assert.equal(cityObjectRows(model, society, agents).length, 5);
  assert.deepEqual(cityObjectRows(model, society, agents, "bank").map(row => [row.kind, row.id]), [["institution", "bank:2"]]);
  assert.deepEqual(cityObjectRows(model, society, agents, "Shop").map(row => row.key), ["firm:3"]);
  assert.equal(cityObjectRows(model, society, agents, "private").length, 0);
  for (const query of ["person", "citizen", "Parent"]) {
    assert.deepEqual(cityObjectRows(model, society, agents, query).map(row => row.key), ["agent:1"]);
  }
  society.households.available = false;
  assert.equal(cityObjectRows(model, society, agents, "household").length, 0);
});

test("city list pagination bounds DOM records and recovers after filters shrink the list", () => {
  const rows = Array.from({ length: 99 }, (_, id) => ({ id }));
  assert.equal(cityObjectPage(rows, 0).rows.length, 40);
  assert.equal(cityObjectPage(rows, 1).rows[0].id, 40);
  assert.equal(cityObjectPage(rows, 999).rows.length, 19);
  assert.equal(cityObjectPage(rows.slice(0, 2), 2).page, 0);
  assert.deepEqual(cityObjectPage([], -1), { page: 0, pages: 1, rows: [] });
  const state = parseObserverViewState(new URLSearchParams("tick=3&household=7&view=list"));
  const returned = new URL(cityWorkspaceHref("run", parseObserverViewState(cityEvidenceParams(state))), "http://local");
  assert.equal(returned.searchParams.get("view"), "list");
  assert.equal(returned.searchParams.get("household"), "7");
});
