import assert from "node:assert/strict";
import test from "node:test";

import {
  appendParticipantHistory,
  buildParticipantAction,
  initialParticipantValues,
  participantActionKey,
} from "../src/participant.js";

test("participant form preserves typed select values and variants", () => {
  const descriptor = {
    type: "apply_loan",
    variant: "firm",
    fields: [
      { name: "firm_id", kind: "hidden", default: 7 },
      { name: "bank_id", kind: "select", options: [{ value: 2, label: "Bank 2" }] },
      { name: "amount", kind: "number", default: 30000 },
    ],
  };

  const initial = initialParticipantValues(descriptor, null);
  assert.deepEqual(initial, { firm_id: 7, bank_id: 2, amount: 30000 });
  assert.equal(participantActionKey(descriptor), "apply_loan:firm");
  assert.deepEqual(buildParticipantAction(descriptor, {
    firm_id: 999,
    bank_id: 2,
    amount: "45000",
  }), {
    type: "apply_loan",
    variant: "firm",
    firm_id: 7,
    bank_id: 2,
    amount: 45000,
  });
});

test("participant history appends cursor pages without duplicate actions", () => {
  const current = { items: [{ id: 3 }, { id: 2 }], next_before_id: 2 };
  const page = { items: [{ id: 2 }, { id: 1 }], next_before_id: null };

  assert.deepEqual(appendParticipantHistory(current, page), {
    items: [{ id: 3 }, { id: 2 }, { id: 1 }],
    next_before_id: null,
  });
});

test("participant form reads and builds nested business ideas", () => {
  const descriptor = {
    type: "found_company",
    fields: [
      { name: "name", kind: "text", default: "New Firm" },
      { name: "mission", kind: "text", action_path: ["business_idea", "mission"] },
      { name: "offering", kind: "text", action_path: ["business_idea", "offering"] },
    ],
  };
  const queued = {
    type: "found_company",
    name: "Queued Firm",
    business_idea: { mission: "Serve neighbors", offering: "Local goods" },
  };

  assert.deepEqual(initialParticipantValues(descriptor, queued), {
    name: "Queued Firm",
    mission: "Serve neighbors",
    offering: "Local goods",
  });
  assert.deepEqual(buildParticipantAction(descriptor, {
    name: "New Firm",
    mission: "Build useful things",
    offering: "Useful goods",
  }), {
    type: "found_company",
    name: "New Firm",
    business_idea: {
      mission: "Build useful things",
      offering: "Useful goods",
    },
  });
});
