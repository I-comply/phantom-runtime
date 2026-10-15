#!/usr/bin/env node
// Runs each PURSUE asset's real demo command against the source tree and records a sanitized transcript.
// Output: data/demos/<slug>.json (public-safe: synthetic inputs only, paths and temp names redacted).
// Fails if the run does not contain every expected string or exits unexpectedly.
import path from "node:path";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, writeFile } from "./lib/util.mjs";

const SRC_ROOT = process.env.PWX_SRC_ROOT || "/home/user/src";
const REPO_ROOT = path.resolve(ROOT, "..");
const FIX = path.join(ROOT, "demo-fixtures");
const rootDir = (r) => (r === "phantom-runtime" ? REPO_ROOT : path.join(SRC_ROOT, r));
const curFile = process.argv.includes("--curation") ? process.argv[process.argv.indexOf("--curation") + 1] : path.join(ROOT, "private/curation/assets.mjs");
const { assets } = await import(pathToFileURL(path.resolve(curFile)).href);

const sanitize = (s) => s
  .replace(/\x1b\[[0-9;]*m/g, "")
  .replaceAll(REPO_ROOT, "<repo>").replaceAll(SRC_ROOT, "<src>").replaceAll(os.homedir(), "~")
  .replace(/\/tmp\/[^\s"']+/g, "/tmp/<tmp>")
  .replace(/"ts": [0-9.]+/g, '"ts": <ts>')
  .replace(/\b(?:\d+\.\d+)s\b/g, "<t>s").replace(/in \d+(\.\d+)?ms/g, "in <t>ms").replace(/Duration\s+\S+ms.*$/gm, "Duration <t>")
  .replace(/Start at\s+\d\d:\d\d:\d\d/g, "Start at <time>");

function run(spec, label) {
  const argv = spec.argv.map((a) => a.replaceAll("{FIXTURES}", FIX));
  const cwd = path.join(rootDir(spec.cwd.split("/")[0]), ...spec.cwd.split("/").slice(1));
  const r = spawnSync(argv[0], argv.slice(1), { cwd, env: { ...process.env, ...(spec.env || {}) }, encoding: "utf8", timeout: 240000 });
  const out = sanitize((r.stdout || "") + (r.stderr ? "\n" + r.stderr : "")).trim();
  const wantExit = spec.expectExit ?? 0;
  const missing = (spec.expect || []).filter((e) => !out.includes(e));
  if (r.status !== wantExit || missing.length) {
    throw new Error(`${label}: exit ${r.status} (want ${wantExit}); missing: ${JSON.stringify(missing)}\n${out.slice(-1500)}`);
  }
  return { command: spec.command, exit_code: r.status, transcript: out.split("\n").slice(0, 120).join("\n") };
}

for (const a of assets) {
  const d = a.demo;
  const runs = [run(d, a.slug), ...(d.extra || []).map((x, i) => run({ ...x, command: x.command }, `${a.slug}#${i + 2}`))];
  writeFile(path.join(ROOT, "data/demos", `${a.slug}.json`), JSON.stringify({
    slug: a.slug, asset_id: `PWX-ASSET-${String(a.n).padStart(6, "0")}`, demo_type: d.type, title: d.title, recorded_on: "2026-10-15",
    environment: { node: process.version, python: spawnSync("python3", ["--version"], { encoding: "utf8" }).stdout.trim() },
    disclosure: "Recorded output of the real code run on synthetic data. Not a hosted service; not production behavior.",
    steps: d.steps, limitations: d.limitations, runs,
  }, null, 2) + "\n");
  console.log("recorded", a.slug, runs.map((r) => r.exit_code).join(","));
}
