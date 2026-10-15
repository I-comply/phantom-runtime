#!/usr/bin/env node
// Validates asset records against schemas/asset.schema.json and cross-checks public data against private records.
// Checks private/assets/*.json when present (full records) and data/assets/*.public.json (public tier) always.
import fs from "node:fs";
import path from "node:path";
import { ROOT, readJson, listJson } from "./lib/util.mjs";
import { validate } from "./lib/schema.mjs";
import { toPublic } from "./lib/tiers.mjs";

const schema = readJson(path.join(ROOT, "schemas/asset.schema.json"));
let bad = 0;
const fail = (m) => { bad++; console.error("FAIL", m); };
const priv = listJson(path.join(ROOT, "private/assets")).map(readJson);
const pub = listJson(path.join(ROOT, "data/assets")).filter((f) => f.endsWith(".public.json")).map(readJson);

const ids = new Set();
for (const r of priv) {
  for (const e of validate(schema, r)) fail(`${r.asset_id}: ${e}`);
  if (ids.has(r.asset_id)) fail(`duplicate ${r.asset_id}`);
  ids.add(r.asset_id);
  for (const rel of r.relationships || []) if (/^PWX-ASSET-/.test(rel.target) && !priv.some((x) => x.asset_id === rel.target)) fail(`${r.asset_id}: dangling relationship ${rel.target}`);
}
for (const p of pub) {
  const r = priv.find((x) => x.asset_id === p.asset_id);
  if (priv.length && !r) fail(`public ${p.asset_id} has no private record`);
  if (r && JSON.stringify(toPublic(r)) !== JSON.stringify(p)) fail(`${p.asset_id}: public file is stale (run npm run register)`);
  if (p.disposition !== "PURSUE") fail(`${p.asset_id}: only PURSUE assets may have public data`);
  if (!p.public?.faq?.length || !p.public?.demo?.expect?.length) fail(`${p.asset_id}: incomplete public package`);
}
console.log(`validated ${priv.length} private record(s), ${pub.length} public record(s)${priv.length ? "" : " (private tier not present; public-tier checks only)"}`);
process.exit(bad ? 1 : 0);
