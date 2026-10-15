import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createServer } from "../src/server.mjs";
import { build } from "./helpers.mjs";

let srv, base, dist, tmp, inquiryFile, metricsFile;
const post = (p, body, headers = { "content-type": "application/json" }) =>
  fetch(base + p, { method: "POST", headers, body: typeof body === "string" ? body : JSON.stringify(body) });
const valid = { name: "Test Buyer", email: "buyer@example.com", org: "Acme", asset: "PWX-ASSET-000001", interest: "acquire", message: "Interested in details.", consent: true, website: "" };
const lines = () => (fs.existsSync(inquiryFile) ? fs.readFileSync(inquiryFile, "utf8").trim().split("\n").filter(Boolean) : []);

before(async () => {
  const b = build(["--staging"]);
  assert.equal(b.status, 0, b.stderr);
  dist = b.out;
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pwx-srv-"));
  inquiryFile = path.join(tmp, "inq", "inquiries.jsonl");
  metricsFile = path.join(tmp, "inq", "metrics.json");
  fs.mkdirSync(path.join(dist, ".secret"), { recursive: true });
  fs.writeFileSync(path.join(dist, ".secret", "x.txt"), "nope");
  srv = createServer({ dist, inquiryFile, metricsFile, inquiryLimit: { max: 12, windowMs: 60000 }, eventLimit: { max: 5, windowMs: 60000 } });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  base = "http://127.0.0.1:" + srv.address().port;
});
after(() => new Promise((r) => srv.close(r)));

test("health endpoint and security headers", async () => {
  const h = await fetch(base + "/healthz");
  assert.equal(h.status, 200);
  assert.deepEqual(await h.json(), { ok: true });
  const r = await fetch(base + "/");
  assert.equal(r.status, 200);
  assert.match(r.headers.get("content-security-policy"), /default-src 'self'/);
  assert.match(r.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.equal(r.headers.get("x-content-type-options"), "nosniff");
  assert.equal(r.headers.get("referrer-policy"), "no-referrer");
});

test("static serving: directory index, 404 page, traversal, dotfiles, manifest and private tier unreachable", async () => {
  assert.equal((await fetch(base + "/assets/ctal-assurance-ledger/")).status, 200);
  assert.equal((await fetch(base + "/no-such-page/")).status, 404);
  for (const p of ["/../package.json", "/%2e%2e/package.json", "/..%2f..%2fetc/passwd", "/.secret/x.txt", "/MANIFEST.sha256.json", "/private/assets/PWX-ASSET-000001.json", "/private/diligence/ctal-assurance-ledger/INDEX.md", "/%00"]) {
    const r = await fetch(base + p);
    assert.ok([400, 404].includes(r.status), `${p} -> ${r.status}`);
  }
  assert.equal((await fetch(base + "/", { method: "DELETE" })).status, 405);
});

test("inquiry: valid submission is stored durably and acknowledged with a reference", async () => {
  const r = await post("/api/inquiry", valid);
  assert.equal(r.status, 201);
  const j = await r.json();
  assert.match(j.reference, /^INQ-[0-9A-F]{10}$/);
  const rows = lines().map((l) => JSON.parse(l));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].reference, j.reference);
  assert.equal(rows[0].email, "buyer@example.com");
  assert.ok(!("website" in rows[0]) && !("ip" in rows[0]));
  assert.equal(fs.statSync(inquiryFile).mode & 0o077, 0, "inquiry file must be owner-only");
});

test("inquiry: validation rejects bad email, empty message, missing consent, unknown asset", async () => {
  for (const [patch, field] of [[{ email: "not-an-email" }, "email"], [{ message: "   " }, "message"], [{ consent: false }, "consent"], [{ asset: "PWX-ASSET-999999" }, "asset"], [{ name: "" }, "name"]]) {
    const r = await post("/api/inquiry", { ...valid, ...patch });
    assert.equal(r.status, 422, field);
    assert.ok((await r.json()).fields.includes(field));
  }
  assert.equal(lines().length, 1, "invalid inquiries must not be stored");
});

test("inquiry: honeypot, content-type, malformed JSON and oversize bodies", async () => {
  const hp = await post("/api/inquiry", { ...valid, website: "http://spam.example" });
  assert.equal(hp.status, 200);
  assert.equal(lines().length, 1, "honeypot submissions are not stored");
  assert.equal((await post("/api/inquiry", "x=1", { "content-type": "text/plain" })).status, 415);
  assert.equal((await post("/api/inquiry", "{not json")).status, 400);
  assert.equal((await post("/api/inquiry", JSON.stringify({ ...valid, message: "a".repeat(20000) }))).status, 413);
  assert.equal((await fetch(base + "/api/inquiry")).status, 405);
});

test("inquiry: control characters are stripped and rate limiting returns 429", async () => {
  const r = await post("/api/inquiry", { ...valid, message: "hello\u0000\u0007 world" });
  assert.equal(r.status, 201);
  assert.equal(JSON.parse(lines().pop()).message, "hello world");
  let last;
  for (let i = 0; i < 6; i++) last = await post("/api/inquiry", valid);
  assert.equal(last.status, 429);
});

test("event counter: allowlisted names only, anonymous, rate limited, flushed to file", async () => {
  assert.equal((await post("/api/event", { name: "cta_click", asset: "PWX-ASSET-000001" })).status, 204);
  assert.equal((await post("/api/event", { name: "evil" })).status, 400);
  assert.equal((await post("/api/event", { name: "cta_click", asset: "../x" })).status, 400);
  for (let i = 0; i < 4; i++) await post("/api/event", { name: "demo_view" });
  assert.equal((await post("/api/event", { name: "demo_view" })).status, 429);
});

test("metrics flush on close contains counts but no identifiers", async () => {
  await new Promise((r) => srv.close(r));
  const m = JSON.parse(fs.readFileSync(metricsFile, "utf8"));
  assert.equal(m["cta_click:PWX-ASSET-000001"], 1);
  assert.ok(m.demo_view >= 1);
  assert.ok(!/\d+\.\d+\.\d+\.\d+/.test(JSON.stringify(m)));
  srv = createServer({ dist, inquiryFile, metricsFile });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  base = "http://127.0.0.1:" + srv.address().port;
});
