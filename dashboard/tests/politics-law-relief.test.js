import test from "node:test";
import assert from "node:assert/strict";
import { normalizePoliticsLawWorkspace } from "../src/workspaces/politicsLawWorkspaceModel.js";

test("legal money rows preserve separate prior credit, collection and held currencies without private payloads", () => {
  const source = { legal: { enabled: true }, matters: [
    { id: 2, monetary_relief: { visibility: "public", award: {
      id: 1, awarded_cents: 170, credited_cents: 100, paid_cents: 20, outstanding_cents: 50,
      currency_code: "CAD", source_account_id: 987, body: "secret-account", payment_basis: "gross_wages",
      tax_cents: 4, net_received_cents: 16, written_off_cents: 0, credited_loss_cents: 0 }, estate_reserve: {
      id: 3, held_cents: 10, status: "pending", currency_code: "USD", escrow_account_id: 765 } } },
    { id: 1, monetary_relief: { visibility: "withheld", award: { id: 4, awarded_cents: 99999, body: "secret-award" } } },
    { id: 3, monetary_relief: { visibility: "public", award: null, estate_reserve: null } },
    { id: 4, requested_remedy: { amount_cents: 500 }, settlement: { enforcement: { paid_cents: 400 } } },
  ] };
  const rows = normalizePoliticsLawWorkspace(source).monetaryRelief;
  assert.deepEqual(rows.map(row => row.id), [1, 2]);
  assert.deepEqual(rows[0], { id: 1, visibility: "withheld", award: null, estate_reserve: null });
  assert.equal(rows[1].award.outstanding_cents, 50);
  assert.equal(rows[1].award.credited_cents, 100);
  assert.equal(rows[1].award.paid_cents, 20);
  assert.equal(rows[1].award.tax_cents, 4);
  assert.equal(rows[1].award.net_received_cents, 16);
  assert.equal(rows[1].award.payment_basis, "gross_wages");
  assert.equal(rows[1].estate_reserve.currency_code, "USD");
  assert.equal(rows[1].award.currency_code, "CAD");
  assert.doesNotMatch(JSON.stringify(rows), /secret|source_account|escrow_account|99999/);
  assert.deepEqual(normalizePoliticsLawWorkspace({ ...source, legal: { enabled: false } }).monetaryRelief, []);
});
