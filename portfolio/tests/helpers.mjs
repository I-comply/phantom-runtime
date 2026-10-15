import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function build(args = [], env = {}) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "pwx-dist-"));
  const r = spawnSync("node", [path.join(ROOT, "scripts/build-site.mjs"), "--out", out, "--no-pdf", ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env },
  });
  return { out, status: r.status, stdout: r.stdout, stderr: r.stderr };
}

export function walk(dir, fn) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, fn);
    else fn(p);
  }
}

export const htmlFiles = (dir) => {
  const o = [];
  walk(dir, (p) => p.endsWith(".html") && o.push(p));
  return o;
};
