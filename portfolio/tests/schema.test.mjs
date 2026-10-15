import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { validate } from "../scripts/lib/schema.mjs";
import { ROOT } from "./helpers.mjs";

const schema = JSON.parse(fs.readFileSync(path.join(ROOT, "schemas/asset.schema.json"), "utf8"));
const privDir = path.join(ROOT, "private/assets");
const records = fs.existsSync(privDir)
  ? fs.readdirSync(privDir).filter((f) => f.endsWith(".json")).map((f) => JSON.parse(fs.readFileSync(path.join(privDir, f), "utf8")))
  : [];
const skipPriv = !records.length && "private records not present";

test("validator rejects wrong types, enums, patterns and missing fields", () => {
  const s = { type: "object", required: ["a"], properties: { a: { type: "string", pattern: "^x" }, b: { enum: [1, 2] }, c: { type: ["number", "null"] } } };
  assert.deepEqual(validate(s, { a: "xy", b: 1, c: null }), []);
  assert.ok(validate(s, {}).some((e) => /missing required "a"/.test(e)));
  assert.ok(validate(s, { a: "y" }).some((e) => /does not match/.test(e)));
  assert.ok(validate(s, { a: "x", b: 3 }).some((e) => /not in enum/.test(e)));
  assert.ok(validate(s, { a: 1 }).some((e) => /expected string/.test(e)));
});

test("asset schema rejects an invalid disposition and malformed id", { skip: skipPriv }, () => {
  const bad = structuredClone(records[0]);
  bad.disposition = "SELL_NOW";
  bad.asset_id = "X-1";
  const errs = validate(schema, bad);
  assert.ok(errs.some((e) => /disposition/.test(e)));
  assert.ok(errs.some((e) => /asset_id/.test(e)));
});

test("every private asset record validates with stable unique IDs", { skip: skipPriv }, () => {
  const ids = new Set();
  for (const r of records) {
    assert.deepEqual(validate(schema, r), [], r.asset_id);
    assert.ok(!ids.has(r.asset_id), "duplicate id " + r.asset_id);
    ids.add(r.asset_id);
  }
});

test("PURSUE records: LOW-confidence provisional valuation, sample size 0, no invented comparables", { skip: skipPriv }, () => {
  for (const r of records.filter((x) => x.disposition === "PURSUE")) {
    assert.equal(r.valuation.pricing_basis, "PROVISIONAL_ESTIMATE");
    assert.equal(r.valuation.sample_size, 0);
    assert.equal(r.valuation.realized_comparable_median, null);
    assert.equal(r.valuation.confidence, "LOW");
    assert.deepEqual(r.market_validation.comparable_closed_sales, []);
    assert.equal(r.buyer_assets.demo_type, "RECORDED_RUN");
    assert.equal(r.publication.approved, false);
  }
});

test("non-PURSUE records are unpriced and unmarketed", { skip: skipPriv }, () => {
  for (const r of records.filter((x) => x.disposition !== "PURSUE")) {
    assert.equal(r.valuation.pricing_basis, "NOT_PRICED");
    assert.equal(r.buyer_assets.demo_type, "NOT_CREATED");
    assert.deepEqual(r.acquisition_packages, []);
  }
});
