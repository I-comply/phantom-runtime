import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { build, htmlFiles, ROOT } from "./helpers.mjs";

const b = build(["--staging"]);
const read = (p) => fs.readFileSync(p, "utf8");
const pages = htmlFiles(b.out).filter((p) => !/\/decks\//.test(p));

test("staging build succeeded", () => assert.equal(b.status, 0, b.stderr));

test("every internal link, script, stylesheet and download resolves to a built file", () => {
  const miss = [];
  for (const f of htmlFiles(b.out)) {
    for (const m of read(f).matchAll(/(?:href|src|action)="([^"#?]+)(?:[?#][^"]*)?"/g)) {
      const u = m[1];
      if (/^(https?:|mailto:|data:)/.test(u) || u.startsWith("/api/")) continue;
      let p = path.join(b.out, u.replace(/^\//, ""));
      if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
      if (!fs.existsSync(p)) miss.push(`${path.relative(b.out, f)} -> ${u}`);
    }
  }
  assert.deepEqual(miss, []);
});

test("accessibility basics: lang, title, single h1, main landmark, skip link, labelled inputs", () => {
  for (const f of pages) {
    const h = read(f), rel = path.relative(b.out, f);
    assert.match(h, /<html lang="en"/, rel);
    assert.match(h, /<title>[^<]{3,}<\/title>/, rel);
    assert.equal((h.match(/<h1[ >]/g) || []).length, 1, rel + " h1 count");
    assert.match(h, /<main id="main">/, rel);
    assert.match(h, /class="skip" href="#main"/, rel);
    for (const m of h.matchAll(/<img\b[^>]*>/g)) assert.match(m[0], /\balt=/, rel);
    for (const m of h.matchAll(/<(?:input|select|textarea)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
      if (/type="(hidden|checkbox)"/.test(m[0]) || /tabindex="-1"/.test(m[0])) continue;
      assert.ok(new RegExp(`for="${m[1]}"`).test(h), `${rel}: no label for #${m[1]}`);
    }
  }
  const css = read(path.join(b.out, "css/site.css"));
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-color-scheme/);
  assert.match(css, /max-width:860px/);
});

test("SEO: canonical, description, og tags, sitemap and robots (staging is noindex)", () => {
  for (const f of pages) {
    const h = read(f);
    assert.match(h, /<link rel="canonical" href="http:\/\/localhost:8080\//);
    assert.match(h, /<meta name="description" content="[^"]{10,}"/);
    assert.match(h, /property="og:title"/);
    assert.match(h, /name="robots" content="noindex,nofollow"/);
  }
  assert.match(read(path.join(b.out, "robots.txt")), /Disallow: \//);
  assert.match(read(path.join(b.out, "sitemap.xml")), /<urlset/);
});

test("catalog lists every staged asset and the client filter works on the real inventory", () => {
  const cat = JSON.parse(read(path.join(b.out, "assets.json")));
  assert.ok(cat.assets.length >= 7);
  const html = read(path.join(b.out, "assets/index.html"));
  for (const a of cat.assets) assert.ok(html.includes(`data-asset-id="${a.asset_id}"`));
  const ctx = vm.createContext({});
  vm.runInContext(read(path.join(ROOT, "public/js/catalog.js")), ctx);
  const F = ctx.PWXCatalog;
  assert.ok(F.filter(cat.assets, { q: "ledger" }).some((a) => /ctal/.test(a.slug)));
  assert.equal(F.filter(cat.assets, { q: "zzzznomatch" }).length, 0);
  assert.ok(F.filter(cat.assets, { category: cat.assets[0].category }).length >= 1);
  assert.equal(F.filter(cat.assets, { maturity: "CONCEPT" }).length, 0);
  assert.ok(F.filter(cat.assets, { type: "SaaS" }).length >= 1);
  assert.equal(F.filter(cat.assets, { q: "scanner", type: "SaaS" }).length, 0);
});

test("asset pages have the required sections in order and honest status labels", () => {
  const order = ["Problem and cost of inaction", "Visual proof", "Verified capabilities", "Not verified", "Why this asset", "Known limitations", "Acquisition options", "Pricing rationale", "Diligence preview", "FAQ"];
  const files = pages.filter((p) => /assets\/[^/]+\/index\.html$/.test(p) && !p.endsWith("assets/index.html"));
  assert.ok(files.length >= 7);
  for (const f of files) {
    const h = read(f);
    let at = 0;
    for (const s of order) {
      const i = h.indexOf(s, at);
      assert.ok(i >= 0, `${f}: missing/out of order "${s}"`);
      at = i;
    }
    assert.match(h, /Request acquisition details/);
    assert.match(h, /provisional/i);
    assert.match(h, /no revenue or customers|No revenue or customers/);
  }
});

test("every PURSUE asset has pitch deck (10-12), short deck (5-7), speaker notes and a demo page", () => {
  const cat = JSON.parse(read(path.join(b.out, "assets.json")));
  for (const a of cat.assets) {
    const pitch = read(path.join(b.out, `decks/${a.slug}-pitch.html`));
    const short = read(path.join(b.out, `decks/${a.slug}-slides.html`));
    const np = (pitch.match(/class="slide"/g) || []).length, ns = (short.match(/class="slide"/g) || []).length;
    assert.ok(np >= 10 && np <= 12, `${a.slug} pitch ${np}`);
    assert.ok(ns >= 5 && ns <= 7, `${a.slug} short ${ns}`);
    assert.equal((pitch.match(/Speaker notes/g) || []).length, np);
    assert.equal((short.match(/Speaker notes/g) || []).length, ns);
    assert.ok(fs.existsSync(path.join(b.out, `decks/${a.slug}-pitch.md`)));
    assert.ok(fs.existsSync(path.join(b.out, `decks/${a.slug}-slides.md`)));
    const demo = read(path.join(b.out, `demos/${a.slug}/index.html`));
    assert.match(demo, /recorded run/i);
    assert.match(demo, /synthetic/i);
  }
});

test("decks are tailored per asset, not one template with a swapped name", () => {
  const body = (f) => [...read(path.join(b.out, f)).matchAll(/<div class="body">([\s\S]*?)<\/div>\s*(?:<span class="draft">|<footer>)/g)].map((m) => m[1].replace(/<[^>]+>/g, " ")).join(" ");
  const x = body("decks/ctal-assurance-ledger-pitch.html"), y = body("decks/replaycheck-event-sourcing-auditor-pitch.html");
  assert.ok(x.length > 2000 && y.length > 2000);
  const wx = new Set(x.split(/\s+/)), wy = new Set(y.split(/\s+/));
  const shared = [...wx].filter((w) => wy.has(w)).length;
  assert.ok(shared / Math.min(wx.size, wy.size) < 0.6, "decks share too much vocabulary: " + shared);
});

test("recorded demo transcripts contain their expected result strings and no local paths", () => {
  const dir = path.join(ROOT, "data/demos");
  const files = fs.readdirSync(dir);
  assert.ok(files.length >= 7);
  for (const f of files) {
    const d = JSON.parse(read(path.join(dir, f)));
    const spec = JSON.parse(read(path.join(ROOT, "data/assets", d.asset_id + ".public.json"))).public.demo;
    for (const e of spec.expect) assert.ok(d.runs.some((r) => r.transcript.includes(e)), `${f}: missing "${e}"`);
    assert.equal(d.demo_type, "RECORDED_RUN");
    assert.match(d.disclosure, /synthetic data/);
    assert.ok(!/\/home\//.test(JSON.stringify(d)));
  }
});

test("inquiry form posts to the working endpoint with consent, honeypot and the verified email fallback", () => {
  const h = read(path.join(b.out, "inquiry/index.html"));
  assert.match(h, /action="\/api\/inquiry"/);
  assert.match(h, /name="consent"[^>]*required/);
  assert.match(h, /name="website"/);
  assert.match(h, /mailto:drs\.vault@proton\.me/);
});

test("content-security-policy compatibility: no inline scripts in pages or decks", () => {
  for (const f of htmlFiles(b.out)) {
    for (const m of read(f).matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      if (/type="application\/ld\+json"/.test(m[1])) continue;
      assert.match(m[1], /\bsrc=/, `${path.relative(b.out, f)} has an inline script`);
    }
  }
});
