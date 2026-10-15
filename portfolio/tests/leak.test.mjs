import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { toPublic, PUBLIC_SCALARS, PUBLIC_ARRAYS, FORBIDDEN_PUBLIC_MARKERS } from "../scripts/lib/tiers.mjs";
import { CONTACT } from "../scripts/lib/contact.mjs";
import { build, walk, ROOT } from "./helpers.mjs";

test("toPublic is deny-by-default: private canaries never survive projection", () => {
  const rec = {
    asset_id: "PWX-ASSET-000099", slug: "x", name: "X",
    source_provenance: [{ locator: "CANARY_LOCATOR" }], ownership: { contributors: ["CANARY_CONTRIB"] },
    valuation: { assumptions: ["CANARY_ASSUMPTION"] }, blockers: ["CANARY_BLOCKER"], next_actions: ["CANARY_NEXT"],
    market_validation: { x: "CANARY_MKT" },
    acquisition_packages: [{ package_name: "p", price: 123456, secret_field: "CANARY_PKG" }],
    public: { headline: "h" }, publication: { approved: false, approved_by: "CANARY_APPROVER" },
  };
  const s = JSON.stringify(toPublic(rec));
  for (const c of ["CANARY_LOCATOR", "CANARY_CONTRIB", "CANARY_ASSUMPTION", "CANARY_BLOCKER", "CANARY_NEXT", "CANARY_MKT", "CANARY_PKG", "CANARY_APPROVER", "123456"]) {
    assert.ok(!s.includes(c), c);
  }
});

test("committed public data files contain only whitelisted top-level keys", () => {
  const dir = path.join(ROOT, "data/assets");
  if (!fs.existsSync(dir)) return;
  const allowed = new Set([...PUBLIC_SCALARS, ...PUBLIC_ARRAYS, "target_buyer", "acquisition_packages", "valuation_public", "public", "publication"]);
  for (const f of fs.readdirSync(dir)) {
    for (const k of Object.keys(JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")))) assert.ok(allowed.has(k), `${f}: ${k}`);
  }
});

test("built site has no forbidden markers, phone number, tel: links or private/local paths", () => {
  const b = build(["--staging"]);
  assert.equal(b.status, 0, b.stderr);
  walk(b.out, (p) => {
    const t = fs.readFileSync(p, "utf8").toLowerCase();
    for (const m of FORBIDDEN_PUBLIC_MARKERS) assert.ok(!t.includes(m.toLowerCase()), `${p}: ${m}`);
    assert.ok(!t.includes(CONTACT.phone), `${p}: phone`);
    assert.ok(!t.includes("tel:"), `${p}: tel link`);
    assert.ok(!/private\/(assets|diligence|inventory)/.test(t), `${p}: private path`);
    assert.ok(!/\/home\/user|\/root\//.test(t), `${p}: local path`);
  });
  assert.ok(!fs.existsSync(path.join(b.out, "private")));
});

test("only the verified owner email appears anywhere in the built site", () => {
  const b = build(["--staging"]);
  const found = new Set();
  walk(b.out, (p) => {
    for (const m of fs.readFileSync(p, "utf8").matchAll(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g)) found.add(m[0].toLowerCase());
  });
  assert.deepEqual([...found], [CONTACT.email]);
});

test("publish gate: production build excludes unapproved assets and is indexable", () => {
  const b = build([], { PWX_SITE_URL: "https://example.test" });
  assert.equal(b.status, 0, b.stderr);
  const cat = JSON.parse(fs.readFileSync(path.join(b.out, "assets.json"), "utf8"));
  assert.equal(cat.assets.length, 0);
  assert.equal(cat.staging, false);
  assert.ok(!fs.existsSync(path.join(b.out, "decks")));
  const robots = fs.readFileSync(path.join(b.out, "robots.txt"), "utf8");
  assert.ok(!/Disallow: \/\n/.test(robots) && /Sitemap: https:\/\/example\.test\/sitemap\.xml/.test(robots));
});

test("production build refuses to run without an https PWX_SITE_URL", () => {
  assert.equal(build([], { PWX_SITE_URL: "" }).status, 2);
  assert.equal(build([], { PWX_SITE_URL: "http://insecure.test" }).status, 2);
});
