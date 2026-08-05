import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildProductNavigation,
  isProductNavigationActive,
} from "../src/lib/productNavigation.js";

const observatorySource = readFileSync(
  new URL("../src/components/Observatory.jsx", import.meta.url), "utf8",
);
const citizenMenuSource = readFileSync(
  new URL("../src/components/CitizenMenu.jsx", import.meta.url), "utf8",
);
const civicStyles = readFileSync(
  new URL("../src/civic-weather-room.css", import.meta.url), "utf8",
);

test("product navigation keeps app and citizenship surfaces on canonical paths", () => {
  const items = buildProductNavigation({
    runId: "run/id",
    worldSlug: "local world",
  });
  assert.deepEqual(
    Object.fromEntries(items.map(item => [item.key, item.href])),
    {
      observatory: "/",
      world_os: "/runs/run%2Fid/overview",
      commons: "/runs/run%2Fid/commons",
      join: "/join/local%20world",
      my_agents: "/my-agents",
    },
  );
  assert.equal(items.find(item => item.key === "join").clientSide, false);
  assert.equal(items.find(item => item.key === "commons").clientSide, true);
});

test("product navigation distinguishes Commons and citizen onboarding", () => {
  assert.equal(
    isProductNavigationActive("world_os", "/runs/run-demo/overview"),
    true,
  );
  assert.equal(
    isProductNavigationActive("world_os", "/runs/run-demo/commons"),
    false,
  );
  assert.equal(
    isProductNavigationActive("commons", "/runs/run-demo/commons"),
    true,
  );
  assert.equal(isProductNavigationActive("join", "/oauth/authorize"), true);
  assert.equal(isProductNavigationActive("my_agents", "/my-agents"), true);
});

test("civic shell styles the citizen menu panel class used by markup", () => {
  assert.match(citizenMenuSource, /className="citizen-menu citizen-menu--panel"/);
  assert.match(civicStyles, /\.world-os-topbar \.citizen-menu--panel \{/);
  assert.match(civicStyles, /\.world-os-topbar \.citizen-menu--panel a \{/);
  assert.doesNotMatch(civicStyles, /citizen-menu-dropdown__panel/);
});

test("hosted observatory does not advertise the unsupported World OS route", () => {
  assert.match(
    observatorySource,
    /\{!hosted && <a[^>]+href=\{`\/runs\/\$\{encodeURIComponent\(status\.run_id\)\}\/overview`\}>Open World OS<\/a>\}/,
  );
  assert.match(observatorySource, /runId=\{hosted \? "" : status\?\.run_id\}/);
});
