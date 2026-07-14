import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationSearchPath,
  normalizeConversationQuery,
} from "../src/conversations.js";

test("conversation search trims, bounds, and encodes the stored-run query", () => {
  assert.equal(normalizeConversationQuery("  bank run  "), "bank run");
  assert.equal(conversationSearchPath("bank run", 500),
    "/api/conversations?limit=200&q=bank+run");
  assert.equal(conversationSearchPath("100% safe", 0),
    "/api/conversations?limit=50&q=100%25+safe");
});

test("blank conversation search preserves the recent-conversation endpoint", () => {
  assert.equal(conversationSearchPath("   ", 16), "/api/conversations?limit=16");
});
