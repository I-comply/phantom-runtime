// Zero-dependency production server: static files + inquiry endpoint + health + privacy-respecting counters.
// Serves ONLY the contents of the built `dist/` directory; the private tier is never reachable from here.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MIME = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml; charset=utf-8" };
const EVENTS = new Set(["cta_click", "demo_view", "deck_view", "catalog_filter", "inquiry_submit"]);
const INTERESTS = new Set(["acquire", "license", "exclusive", "diligence", "other"]);
const EMAIL = /^[^\s@<>"']{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,}$/;
const ASSET_ID = /^PWX-ASSET-[0-9]{6}$/;

export function createServer(opts = {}) {
  const dist = path.resolve(opts.dist || process.env.PWX_DIST || path.join(ROOT, "dist"));
  const inquiryFile = path.resolve(opts.inquiryFile || process.env.PWX_INQUIRY_FILE || path.join(ROOT, "data/inquiries/inquiries.jsonl"));
  const metricsFile = path.resolve(opts.metricsFile || process.env.PWX_METRICS_FILE || path.join(ROOT, "data/inquiries/metrics.json"));
  const trustProxy = opts.trustProxy ?? process.env.PWX_TRUST_PROXY === "1";
  const tls = opts.behindTls ?? process.env.PWX_BEHIND_TLS === "1";
  const limits = { inquiry: opts.inquiryLimit || { max: 5, windowMs: 10 * 60_000 }, event: opts.eventLimit || { max: 120, windowMs: 60_000 } };
  const hits = new Map(); // key -> [timestamps]; in-memory only, never persisted
  const counters = {}; let flushTimer = null;
  let knownAssets = null;
  try { knownAssets = new Set(JSON.parse(fs.readFileSync(path.join(dist, "assets.json"), "utf8")).assets.map((a) => a.asset_id)); } catch { /* no catalog yet */ }

  const limited = (kind, ip) => {
    const { max, windowMs } = limits[kind], key = kind + "|" + ip, now = Date.now();
    const arr = (hits.get(key) || []).filter((t) => now - t < windowMs);
    if (arr.length >= max) { hits.set(key, arr); return true; }
    arr.push(now); hits.set(key, arr);
    if (hits.size > 5000) for (const [k, v] of hits) if (!v.length || now - v[v.length - 1] > 3600_000) hits.delete(k);
    return false;
  };
  const clientIp = (req) => (trustProxy && req.headers["x-forwarded-for"] ? String(req.headers["x-forwarded-for"]).split(",")[0].trim() : req.socket.remoteAddress) || "unknown";

  const secHeaders = () => ({
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()", "Cross-Origin-Opener-Policy": "same-origin",
    ...(tls ? { "Strict-Transport-Security": "max-age=31536000; includeSubDomains" } : {}),
  });
  const send = (res, code, body, headers = {}) => { res.writeHead(code, { ...secHeaders(), ...headers }); res.end(body); };
  const json = (res, code, obj) => send(res, code, JSON.stringify(obj), { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });

  function readBody(req, max) {
    return new Promise((resolve, reject) => {
      let size = 0; const chunks = [];
      req.on("data", (c) => { size += c.length; if (size > max) { req.removeAllListeners("data"); req.resume(); reject(Object.assign(new Error("too large"), { code: 413 })); } else chunks.push(c); });
      req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
      req.on("error", reject);
    });
  }
  const clean = (s, max) => String(s ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").trim().slice(0, max);

  function validateInquiry(b) {
    const out = {}, bad = [];
    out.name = clean(b.name, 120); if (!out.name) bad.push("name");
    out.email = clean(b.email, 200); if (!EMAIL.test(out.email)) bad.push("email");
    out.org = clean(b.org, 160);
    out.message = clean(b.message, 4000); if (!out.message) bad.push("message");
    out.interest = INTERESTS.has(b.interest) ? b.interest : "other";
    out.asset = clean(b.asset, 20);
    if (out.asset && (!ASSET_ID.test(out.asset) || (knownAssets && !knownAssets.has(out.asset)))) bad.push("asset");
    if (b.consent !== true) bad.push("consent");
    return { out, bad };
  }

  async function inquiry(req, res) {
    if (!/^application\/json\b/i.test(req.headers["content-type"] || "")) return json(res, 415, { error: "Content-Type must be application/json" });
    if (limited("inquiry", clientIp(req))) return json(res, 429, { error: "Too many requests. Please try again later or use email." });
    let raw; try { raw = await readBody(req, 16 * 1024); } catch (e) { res.setHeader("Connection", "close"); return json(res, e.code === 413 ? 413 : 400, { error: "Request too large or unreadable." }); }
    let body; try { body = JSON.parse(raw); } catch { return json(res, 400, { error: "Invalid JSON." }); }
    if (!body || typeof body !== "object" || Array.isArray(body)) return json(res, 400, { error: "Invalid body." });
    const reference = "INQ-" + crypto.randomBytes(5).toString("hex").toUpperCase();
    if (typeof body.website === "string" && body.website.trim() !== "") return json(res, 200, { ok: true, reference }); // honeypot: pretend success, store nothing
    const { out, bad } = validateInquiry(body);
    if (bad.length) return json(res, 422, { error: "Please correct the highlighted fields.", fields: bad });
    try {
      fs.mkdirSync(path.dirname(inquiryFile), { recursive: true, mode: 0o700 });
      const fd = fs.openSync(inquiryFile, "a", 0o600);
      try { fs.writeSync(fd, JSON.stringify({ reference, received_at: new Date().toISOString(), ...out }) + "\n"); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    } catch (e) { console.error("inquiry store failed:", e.code || "error"); return json(res, 500, { error: "Could not record your inquiry. Please use the email address on this site." }); }
    console.log(`inquiry received ref=${reference}`); // no personal data in logs
    return json(res, 201, { ok: true, reference });
  }

  async function event(req, res) {
    if (limited("event", clientIp(req))) return json(res, 429, { error: "rate limited" });
    let b; try { b = JSON.parse(await readBody(req, 1024)); } catch { return json(res, 400, { error: "bad request" }); }
    if (!b || !EVENTS.has(b.name) || (b.asset != null && !ASSET_ID.test(String(b.asset)))) return json(res, 400, { error: "unknown event" });
    const k = b.asset ? `${b.name}:${b.asset}` : b.name; counters[k] = (counters[k] || 0) + 1;
    if (!flushTimer) flushTimer = setTimeout(flush, 5000).unref();
    return send(res, 204, "");
  }
  function flush() {
    flushTimer = null;
    try { fs.mkdirSync(path.dirname(metricsFile), { recursive: true }); let cur = {}; try { cur = JSON.parse(fs.readFileSync(metricsFile, "utf8")); } catch { /* new */ }
      for (const [k, v] of Object.entries(counters)) { cur[k] = (cur[k] || 0) + v; delete counters[k]; }
      fs.writeFileSync(metricsFile, JSON.stringify(cur, null, 2)); } catch (e) { console.error("metrics flush failed:", e.code || "error"); }
  }

  function serveStatic(req, res, pathname) {
    let rel; try { rel = decodeURIComponent(pathname); } catch { return send(res, 400, "Bad request"); }
    if (rel.includes("\0") || rel.split("/").some((s) => s === ".." || s.startsWith("."))) return notFound(res);
    let file = path.join(dist, rel);
    if (!file.startsWith(dist + path.sep) && file !== dist) return notFound(res);
    try { const st = fs.statSync(file); if (st.isDirectory()) file = path.join(file, "index.html"); } catch { return notFound(res); }
    if (path.basename(file) === "MANIFEST.sha256.json") return notFound(res);
    let data; try { data = fs.readFileSync(file); } catch { return notFound(res); }
    const ext = path.extname(file).toLowerCase();
    const h = { "Content-Type": MIME[ext] || "application/octet-stream", "Cache-Control": ext === ".html" ? "no-cache" : "public, max-age=3600", ETag: '"' + crypto.createHash("sha1").update(data).digest("hex") + '"' };
    if (req.headers["if-none-match"] === h.ETag) return send(res, 304, "", h);
    return send(res, 200, req.method === "HEAD" ? "" : data, h);
  }
  function notFound(res) {
    let body = "Not found"; try { body = fs.readFileSync(path.join(dist, "404.html")); } catch { /* default */ }
    return send(res, 404, body, { "Content-Type": "text/html; charset=utf-8" });
  }

  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://x"); const p = url.pathname;
      if (p === "/healthz") return json(res, 200, { ok: true });
      if (p === "/api/inquiry") return req.method === "POST" ? await inquiry(req, res) : json(res, 405, { error: "POST only" });
      if (p === "/api/event") return req.method === "POST" ? await event(req, res) : json(res, 405, { error: "POST only" });
      if (p.startsWith("/api/")) return json(res, 404, { error: "not found" });
      if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "Method not allowed", { Allow: "GET, HEAD" });
      return serveStatic(req, res, p);
    } catch (e) { console.error("unhandled:", e.code || e.name); if (!res.headersSent) json(res, 500, { error: "internal error" }); else res.end(); }
  });
  server.requestTimeout = 15_000; server.headersTimeout = 10_000; server.keepAliveTimeout = 5_000;
  server.on("close", flush);
  return server;
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  const port = Number(process.env.PORT || 8080), host = process.env.HOST || "127.0.0.1";
  const s = createServer();
  s.listen(port, host, () => console.log(`portfolio listening on http://${host}:${port}`));
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => s.close(() => process.exit(0)));
}
