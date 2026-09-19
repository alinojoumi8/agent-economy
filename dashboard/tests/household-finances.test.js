import assert from "node:assert/strict";
import test from "node:test";
import { cashGiniLabel, financeMoney, householdFinanceFrameMatches } from "../src/workspaces/householdFinancesModel.js";

test("financial frames cannot cross run, fork, tick, person or authorization scope", () => {
  const scope = { runId: "run-a", fork: null, tick: 3, agentId: 7 };
  const frame = { run_id: "run-a", fork_id: null, tick: 3, semantics_version: 20,
    projection: "operator.household-finances", data: { requested_tick: "3", selected_agent_id: 7,
      contract_version: "household-finances-v1", visibility: "local_operator" } };
  assert.equal(householdFinanceFrameMatches(frame, scope), true);
  for (const change of [{ run_id: "run-b" }, { fork_id: "fork-b" }, { tick: 4 }, { semantics_version: 19 }, { projection: "world.map" }]) {
    assert.equal(householdFinanceFrameMatches({ ...frame, ...change }, scope), false);
  }
  for (const change of [{ requested_tick: "live" }, { selected_agent_id: 8 }, { visibility: "public" }, { contract_version: "future" }]) {
    assert.equal(householdFinanceFrameMatches({ ...frame, data: { ...frame.data, ...change } }, scope), false);
  }
  assert.equal(householdFinanceFrameMatches(null, scope), false);
});

test("cash display keeps currency, real zero, negative cash and missing values distinct", () => {
  assert.equal(financeMoney(0, "NSD"), "0.00 NSD");
  assert.equal(financeMoney(-125, "USD"), "-1.25 USD");
  assert.equal(financeMoney(null, "USD"), "Unavailable");
  assert.equal(financeMoney(NaN, "USD"), "Unavailable");
  assert.equal(cashGiniLabel(undefined), "Unavailable");
  assert.equal(cashGiniLabel({ gini: 0, population_count: 0, nonnegative_cash_cents: 0 }), "Empty cohort (0 by convention)");
  assert.equal(cashGiniLabel({ gini: 0, population_count: 4, nonnegative_cash_cents: 0 }), "No positive cash (0 by convention)");
  assert.equal(cashGiniLabel({ gini: 1 / 3, population_count: 3, nonnegative_cash_cents: 300 }), "0.333");
});
