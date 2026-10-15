#!/usr/bin/env node
// Static site + buyer-package generator. Reads PUBLIC-tier data only (data/assets/*.public.json, data/demos/*.json).
// Usage: node scripts/build-site.mjs [--staging] [--data DIR] [--out DIR] [--no-pdf]
//   production (default): only publication.approved assets; requires PWX_SITE_URL (https origin).
//   --staging: includes unapproved assets with banners + noindex; site URL defaults to http://localhost:8080.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { ROOT, esc, readJson, writeFile, listJson, usd } from "./lib/util.mjs";
import { CONTACT } from "./lib/contact.mjs";
import { pitchSlides, shortSlides, deckHtml, deckMarkdown } from "./lib/decks.mjs";
import { FORBIDDEN_PUBLIC_MARKERS } from "./lib/tiers.mjs";

const argv = process.argv.slice(2);
const flag = (n) => argv.includes(n);
const opt = (n, d) => (argv.includes(n) ? argv[argv.indexOf(n) + 1] : d);
const STAGING = flag("--staging");
const DATA = path.resolve(opt("--data", path.join(ROOT, "data")));
const OUT = path.resolve(opt("--out", path.join(ROOT, "dist")));
const SITE = (process.env.PWX_SITE_URL || (STAGING ? "http://localhost:8080" : "")).replace(/\/$/, "");
if (!SITE) { console.error("PWX_SITE_URL is required for a production build (e.g. https://your-domain)."); process.exit(2); }
if (!STAGING && !/^https:\/\//.test(SITE)) { console.error("Production PWX_SITE_URL must be https://"); process.exit(2); }

const BRAND = "PhantomworX + i-Comply";
const COPY = "© 2026 Daniel Ron Stevens. All Rights Reserved.";
let all = listJson(path.join(DATA, "assets")).map(readJson);
const demos = Object.fromEntries(listJson(path.join(DATA, "demos")).map((f) => { const d = readJson(f); return [d.slug, d]; }));
const assets = all.filter((a) => STAGING || a.publication.approved).sort((x, y) => x.asset_id.localeCompare(y.asset_id));
const chip = (m) => String(m).replaceAll("_", " ").toLowerCase();
const range = (r) => (r && r[0] != null ? `${usd(r[0])}–${usd(r[1])}` : "on request");
const isDraft = (a) => !a.publication.approved;

fs.rmSync(OUT, { recursive: true, force: true });
fs.cpSync(path.join(ROOT, "public"), OUT, { recursive: true });

const logo = `<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><rect width="32" height="32" rx="8" fill="#10141b"/><path d="M8 22V10l8-4 8 4v12l-8 4z" fill="none" stroke="#6ee7d4" stroke-width="2" stroke-linejoin="round"/><path d="M16 6v20M8 10l16 12M24 10 8 22" stroke="#8b9cff" stroke-width="1.2" opacity=".7"/></svg>`;
function layout({ title, desc, path: p, body, current = "", noindex = false, jsonld = null }) {
  const url = SITE + p;
  const robots = STAGING || noindex ? '<meta name="robots" content="noindex,nofollow">' : "";
  const nav = [["/assets/", "Assets"], ["/how-acquisition-works/", "How it works"], ["/about/", "About"], ["/inquiry/", "Request details"]]
    .map(([h, t]) => `<a href="${h}"${current === h ? ' aria-current="page"' : ""}>${t}</a>`).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><meta name="description" content="${esc(desc)}">${robots}
<link rel="canonical" href="${esc(url)}"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="theme-color" content="#0a0c10">
<meta property="og:type" content="website"><meta property="og:site_name" content="${BRAND}"><meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(desc)}"><meta property="og:url" content="${esc(url)}">
<meta name="twitter:card" content="summary"><link rel="stylesheet" href="/css/site.css">${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld).replace(/</g, "\\u003c")}</script>` : ""}</head>
<body><a class="skip" href="#main">Skip to content</a>${STAGING ? '<div class="staging" role="status">STAGING PREVIEW — content not yet approved for publication</div>' : ""}
<header class="site"><div class="wrap"><a class="brand" href="/" aria-label="${BRAND} home">${logo}<span>PhantomworX<span class="plus">+</span>i-Comply</span></a><nav class="main" aria-label="Primary">${nav}</nav></div></header>
<main id="main">${body}</main>
<footer class="site"><div class="wrap"><div><strong>${BRAND}</strong><br>Principal: Daniel Ron Stevens<br>${COPY}</div>
<div><a href="/privacy/">Privacy</a> · <a href="/how-acquisition-works/">Acquisition process</a>${CONTACT.publish_email ? ` · <a href="mailto:${CONTACT.email}">${CONTACT.email}</a>` : ""}</div>
<div class="faint">Prices are provisional estimates. Nothing here is legal, tax or investment advice.</div></div></footer>
<script src="/js/track.js" defer></script></body></html>`;
}

const cta = (a, label = "Request acquisition details") => `<a class="btn primary" data-track="cta_click" data-asset="${esc(a?.asset_id || "")}" href="/inquiry/${a ? `?asset=${encodeURIComponent(a.asset_id)}` : ""}">${label}</a>`;
const badges = (a) => `<div class="badges"><span class="badge acc">${esc(chip(a.maturity))}</span><span class="badge ${/PASSING/.test(a.test_status) ? "ok" : "warn"}">${esc(chip(a.test_status))}</span><span class="badge">${esc(a.asset_type)}</span><span class="badge">no revenue or customers claimed</span>${isDraft(a) ? '<span class="badge warn">draft</span>' : ""}</div>`;

function card(a) {
  return `<article class="card" data-asset-id="${a.asset_id}"><h3><a href="/assets/${a.slug}/">${esc(a.name)}</a></h3>${badges(a)}<p>${esc(a.one_line_value_proposition)}</p><p class="price">${esc(range(a.valuation_public.range))} <small>provisional source-transfer range</small></p></article>`;
}

// ───── Home
function home() {
  const featured = assets.slice(0, 6);
  const body = `<section class="hero"><div class="wrap"><p class="eyebrow">Digital asset catalog · acquisition-ready software</p>
<h1>Tested software and IP, packaged for acquisition.</h1>
<p class="lede">${assets.length ? `${assets.length} evidence-backed technology assets, each with its own demo, deck and diligence trail. Maturity, test status and known limits are stated on every page — claims we cannot verify are not made.` : "The catalog is being finalized. Request details to be notified."}</p>
<div class="cta-row"><a class="btn primary" href="/assets/">Explore assets</a>${cta(null)}</div></div></section>
<section class="block"><div class="wrap"><h2>Featured assets</h2><div class="grid">${featured.map(card).join("") || '<p class="muted">No assets are published yet.</p>'}</div></div></section>
<section class="block"><div class="wrap"><h2>Browse by buyer problem</h2><div class="grid">${[...new Set(assets.map((a) => a.category))].sort().map((c) => `<a class="card" style="text-decoration:none" href="/assets/?category=${encodeURIComponent(c)}"><h3>${esc(c)}</h3><p>${assets.filter((a) => a.category === c).length} asset(s)</p></a>`).join("")}</div></div></section>
<section class="block"><div class="wrap two"><div><h2>What “verified” means here</h2><p class="muted">Every capability listed on an asset page is backed by a dated test run or file inspection. Revenue, customers and usage are not claimed for any asset. Prices are provisional estimates with a stated model and confidence level, not realized-sale averages.</p></div>
<div class="notice"><strong>Contact.</strong> Use the <a href="/inquiry/">inquiry form</a>${CONTACT.publish_email ? ` or email <a href="mailto:${CONTACT.email}">${CONTACT.email}</a>` : ""}.</div></div></section>`;
  return layout({ title: `${BRAND} — acquisition-ready software assets`, desc: "Evidence-backed software and IP assets with demos, decks and diligence trails. Request acquisition details.", path: "/", body, jsonld: { "@context": "https://schema.org", "@type": "Organization", name: BRAND, founder: { "@type": "Person", name: "Daniel Ron Stevens" }, url: SITE + "/" } });
}

// ───── Catalog
function catalog() {
  const cats = [...new Set(assets.map((a) => a.category))].sort(), mats = [...new Set(assets.map((a) => a.maturity))].sort(), types = [...new Set(assets.map((a) => a.asset_type))].sort();
  const opts = (xs, fmt = (x) => x) => xs.map((x) => `<option value="${esc(x)}">${esc(fmt(x))}</option>`).join("");
  const body = `<section class="block"><div class="wrap"><h1>Asset catalog</h1><p class="lede">Search and filter. Every listing shows maturity, test status and a provisional price range.</p>
<form id="catalog-filters" class="filters" role="search" hidden aria-label="Filter assets"><div><label for="q">Search</label><input id="q" name="q" type="search" placeholder="e.g. ledger, scanner, workflow" autocomplete="off"></div>
<div><label for="category">Category</label><select id="category" name="category"><option value="">All</option>${opts(cats)}</select></div>
<div><label for="maturity">Maturity</label><select id="maturity" name="maturity"><option value="">All</option>${opts(mats, chip)}</select></div>
<div><label for="type">Type</label><select id="type" name="type"><option value="">All</option>${opts(types)}</select></div></form>
<p id="catalog-status" class="muted" role="status" aria-live="polite"></p>
<div class="grid" id="catalog-grid">${assets.map(card).join("") || '<p class="muted">No assets are published yet.</p>'}</div></div></section>
<script src="/js/catalog.js" defer></script>
`;
  return layout({ title: `Asset catalog — ${BRAND}`, desc: "Browse tested software and IP assets with maturity, test status and provisional pricing.", path: "/assets/", body, current: "/assets/" });
}

// ───── Asset page
function flow(line) { const parts = line.split("→").map((s) => s.trim()).filter(Boolean); return parts.length > 1 ? `<div class="flow" role="img" aria-label="Architecture flow">${parts.map((p, i) => `${i ? '<span class="a" aria-hidden="true">→</span>' : ""}<span class="n">${esc(p)}</span>`).join("")}</div>` : `<p>${esc(line)}</p>`; }
function assetPage(a) {
  const p = a.public, v = a.valuation_public, d = demos[a.slug];
  const pk = a.acquisition_packages;
  const body = `<article><section class="block"><div class="wrap"><p class="crumbs"><a href="/">Home</a> / <a href="/assets/">Assets</a> / ${esc(a.name)}</p>
${isDraft(a) ? '<div class="notice" role="note"><strong>Draft.</strong> Not yet approved for publication by the owner.</div><br>' : ""}
<p class="eyebrow">${esc(a.category)} · ${esc(a.asset_id)}</p><h1>${esc(p.headline)}</h1><p class="lede">${esc(p.subheadline)}</p>${badges(a)}<br>
<div class="cta-row">${cta(a)}<a class="btn ghost" href="/demos/${a.slug}/" data-track="demo_view" data-asset="${a.asset_id}">View demo</a><a class="btn ghost" href="/decks/${a.slug}-pitch.html" data-track="deck_view" data-asset="${a.asset_id}">Pitch deck</a></div></div></section>
<section class="block"><div class="wrap two"><div><h2>Problem and cost of inaction</h2><p>${esc(a.buyer_problem)}</p><p class="muted">${esc(p.cost_of_inaction)}</p>
<h2 style="margin-top:28px">Solution</h2><p>${esc(a.solution_summary_public)}</p></div>
<div><h2>Visual proof</h2>${p.architecture_public.map(flow).join("")}${d ? `<div class="term-head"><span>Recorded run · ${esc(d.demo_type.replaceAll("_", " ").toLowerCase())}</span><span>${esc(d.recorded_on)}</span></div><pre class="term" tabindex="0" aria-label="Recorded terminal output">$ ${esc(p.demo.command)}\n${esc(d.runs[0].transcript.split("\n").slice(0, 14).join("\n"))}\n…</pre>` : ""}</div></div></section>
<section class="block"><div class="wrap two"><div><h2>Verified capabilities</h2><ul class="clean">${a.verified_capabilities.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
<h3 style="margin-top:24px">Not verified</h3><ul class="clean unv">${a.unverified_claims.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
<div><h2>Why this asset</h2><ul class="clean">${a.differentiators_public.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
<h3 style="margin-top:24px">Known limitations</h3><ul class="clean lim">${p.public_limitations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div></section>
<section class="block"><div class="wrap"><h2>Demo</h2><p>${esc(p.demo.title)}. <a href="/demos/${a.slug}/">Open the demo page</a> — ${esc(p.demo.limitations)}</p></div></section>
<section class="block"><div class="wrap"><h2>Acquisition options</h2><div class="tablewrap"><table class="t"><thead><tr><th scope="col">Package</th><th scope="col">Provisional range (USD)</th><th scope="col">Rights</th><th scope="col">Excludes</th><th scope="col">Availability</th></tr></thead><tbody>
${pk.map((x) => `<tr><th scope="row">${esc(x.package_name)}</th><td>${esc(range(x.price_range))}</td><td>${esc(x.rights_granted)}</td><td>${esc((x.exclusions || []).join("; "))}</td><td>${esc(x.availability || "")}</td></tr>`).join("")}</tbody></table></div>
<h3 style="margin-top:28px">Pricing rationale</h3><p>${esc(v.statement)}</p><p class="muted">Basis: ${esc(v.pricing_basis.replaceAll("_", " ").toLowerCase())} · confidence: ${esc(v.confidence.toLowerCase())}. Terms are subject to counsel-reviewed agreements; payment and escrow mechanisms are agreed separately and are not implemented on this site.</p></div></section>
<section class="block"><div class="wrap"><h2>Diligence preview</h2><ul class="clean">${p.diligence_preview.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><p class="muted">Detailed architecture, source walkthrough, SBOM and the comparable-sales memo are shared under NDA.</p></div></section>
<section class="block"><div class="wrap"><h2>FAQ</h2>${p.faq.map((f) => `<details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join("")}</div></section>
</article><div class="sticky-cta"><div class="wrap"><span class="muted">${esc(a.name)} · ${esc(range(v.range))}</span>${cta(a)}</div></div>`;
  const jsonld = { "@context": "https://schema.org", "@type": "SoftwareApplication", name: a.name, applicationCategory: a.category, description: a.one_line_value_proposition, creator: { "@type": "Person", name: a.creator_attribution } };
  return layout({ title: `${a.name} — ${BRAND}`, desc: a.one_line_value_proposition, path: `/assets/${a.slug}/`, body, current: "/assets/", noindex: isDraft(a), jsonld });
}

// ───── Demo page
function demoPage(a) {
  const d = demos[a.slug]; if (!d) throw new Error(`no demo recorded for ${a.slug}`);
  const body = `<section class="block"><div class="wrap"><p class="crumbs"><a href="/assets/${a.slug}/">${esc(a.name)}</a> / Demo</p><h1>${esc(d.title)}</h1>
<div class="notice"><strong>${esc(d.demo_type.replaceAll("_", " "))}.</strong> ${esc(d.disclosure)}</div>
<h2 style="margin-top:28px">What you will see</h2><ol class="steps">${d.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
${d.runs.map((r, i) => `<h2 style="margin-top:28px">${i ? "Follow-up run" : "Recorded output"}</h2><div class="term-head"><span>$ ${esc(r.command)}</span><span>exit code ${r.exit_code}</span></div><pre class="term" tabindex="0">${esc(r.transcript)}</pre>`).join("")}
<h2 style="margin-top:28px">Limitations</h2><p>${esc(d.limitations)}</p>
<h2>Reproduce</h2><p class="muted">Recorded on ${esc(d.recorded_on)} with ${esc(d.environment.python)} and Node ${esc(d.environment.node)}. Reproduction commands and the verification test are provided in the diligence package. Inputs are synthetic; no credentials or customer data are involved.</p>
<div class="cta-row">${cta(a)}<a class="btn ghost" href="/decks/${a.slug}-slides.html">Meeting slides</a></div></div></section>`;
  return layout({ title: `Demo: ${a.name} — ${BRAND}`, desc: `Recorded run of ${a.name} on synthetic data.`, path: `/demos/${a.slug}/`, body, current: "/assets/", noindex: isDraft(a) });
}

// ───── Static pages
function how() {
  const steps = [["Inquiry", "Submit the inquiry form or email. Provide your organization and the asset of interest."], ["Qualification", "We confirm fit and intent. No payment details or sensitive documents are requested at this stage."], ["NDA where appropriate", "A mutual NDA precedes access to confidential architecture, source walkthroughs and the comparable-sales memo."], ["Controlled diligence", "Diligence materials are shared through an access-controlled channel agreed with you."], ["Offer", "You propose terms against one of the listed packages; prices on this site are provisional starting points."], ["Agreement", "Counsel-reviewed agreement defining rights, exclusions, warranties and acceptance criteria."], ["Secure transfer and handover", "Tagged source snapshot, checksums, documentation and a handover session, per the agreement."]];
  const body = `<section class="block"><div class="wrap"><h1>How acquisition works</h1><p class="lede">A transparent path from inquiry to handover.</p><ol class="steps">${steps.map(([t, d]) => `<li><h3>${t}</h3><p class="muted" style="margin:0">${d}</p></li>`).join("")}</ol>
<div class="notice" style="margin-top:28px"><strong>Important.</strong> Legal agreements, payment and escrow are handled through separately configured and verified processes. This website does not take payments or hold funds.</div><br>${cta(null)}</div></section>`;
  return layout({ title: `How acquisition works — ${BRAND}`, desc: "Inquiry, qualification, NDA, diligence, offer, agreement and handover.", path: "/how-acquisition-works/", body, current: "/how-acquisition-works/" });
}
function about() {
  const body = `<section class="block"><div class="wrap two"><div><h1>About and provenance</h1><p class="lede">${BRAND} is the studio brand for software and IP created by Daniel Ron Stevens.</p>
<h2>Evidence standard</h2><p>Statements about capabilities are limited to what a dated test run or file inspection supports. Where an asset's code was produced with AI assistance, that is disclosed in diligence and ownership review is a precondition of any rights grant. No customers, revenue, awards or testimonials are claimed.</p>
<h2>What this is not</h2><p class="muted">Not a law firm, broker or escrow agent. Nothing here is legal, tax or investment advice.</p></div>
<div class="card"><h3>Attribution</h3><p>Principal: Daniel Ron Stevens</p><p>Brand: ${BRAND}</p><p>${COPY}</p><p>Contact: <a href="/inquiry/">inquiry form</a>${CONTACT.publish_email ? ` · <a href="mailto:${CONTACT.email}">${CONTACT.email}</a>` : ""}</p></div></div></section>`;
  return layout({ title: `About — ${BRAND}`, desc: "Founder attribution, evidence standard and provenance approach.", path: "/about/", body, current: "/about/" });
}
function inquiry() {
  const body = `<section class="block"><div class="wrap two"><div><h1>Request acquisition details</h1><p class="lede">Tell us what you are evaluating. We collect only what is needed to reply.</p>
<form id="inquiry-form" method="post" action="/api/inquiry" novalidate>
<div class="hp" aria-hidden="true"><label for="website">Leave this empty</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>
<p><label for="name">Name</label><input id="name" name="name" required maxlength="120" autocomplete="name"></p>
<p><label for="email">Work email</label><input id="email" name="email" type="email" required maxlength="200" autocomplete="email"></p>
<p><label for="org">Organization</label><input id="org" name="org" maxlength="160" autocomplete="organization"></p>
<p><label for="asset">Asset of interest</label><select id="asset" name="asset"><option value="">General inquiry</option>${assets.map((a) => `<option value="${a.asset_id}">${esc(a.name)}</option>`).join("")}</select></p>
<p><label for="interest">Interest</label><select id="interest" name="interest"><option value="acquire">Acquire (source transfer)</option><option value="license">License</option><option value="exclusive">Exclusive rights</option><option value="diligence">Confidential diligence</option><option value="other">Other</option></select></p>
<p><label for="message">Message</label><textarea id="message" name="message" required maxlength="4000"></textarea></p>
<p><label style="display:flex;gap:10px;align-items:flex-start"><input type="checkbox" name="consent" required style="width:auto;min-height:0;margin-top:5px"> <span>I agree to be contacted about this inquiry and to the <a href="/privacy/">privacy notice</a>.</span></label></p>
<p class="muted">Do not include payment details, credentials or confidential documents in this form.</p>
<button class="btn primary" type="submit">Send inquiry</button></form>
<div id="inquiry-result" role="status" aria-live="polite" hidden></div></div>
<div class="card"><h3>Prefer email?</h3>${CONTACT.publish_email ? `<p><a href="mailto:${CONTACT.email}">${CONTACT.email}</a></p>` : "<p>Use the form.</p>"}<p class="muted">Quote the asset ID if you have one. No response-time guarantee is made.</p></div></div></section>
<script src="/js/inquiry.js" defer></script>`;
  return layout({ title: `Request acquisition details — ${BRAND}`, desc: "Secure inquiry form for acquisition, licensing and diligence requests.", path: "/inquiry/", body, current: "/inquiry/" });
}
function privacy() {
  const body = `<section class="block"><div class="wrap"><h1>Privacy notice</h1>
<h2>What the inquiry form collects</h2><p>Name, email, optional organization, asset of interest, interest type and your message. Nothing else is requested. Do not submit payment details or confidential documents.</p>
<h2>Why and how long</h2><p>To reply to your inquiry. Inquiries are stored on the operator's server and kept only as long as needed to handle the request, then deleted on request.</p>
<h2>Technical data</h2><p>The server applies per-address rate limiting using a short-lived in-memory counter and does not store IP addresses with inquiries. The site sets no cookies and uses no third-party analytics. A first-party counter records anonymous event names (for example, "inquiry submitted") with no identifiers; browsers sending Do Not Track are not counted.</p>
<h2>Your choices</h2><p>Email${CONTACT.publish_email ? ` <a href="mailto:${CONTACT.email}">${CONTACT.email}</a>` : " the operator"} to request access to or deletion of your inquiry.</p>
<p class="muted">${COPY}</p></div></section>`;
  return layout({ title: `Privacy — ${BRAND}`, desc: "What the inquiry form collects and how it is handled.", path: "/privacy/", body });
}
function notFound() { return layout({ title: `Not found — ${BRAND}`, desc: "Page not found.", path: "/404.html", noindex: true, body: `<section class="block"><div class="wrap"><h1>Page not found</h1><p><a href="/">Return home</a> or <a href="/assets/">browse assets</a>.</p></div></section>` }); }

// ───── Emit
const W = (rel, html) => writeFile(path.join(OUT, rel), html);
W("index.html", home()); W("assets/index.html", catalog()); W("how-acquisition-works/index.html", how()); W("about/index.html", about());
W("inquiry/index.html", inquiry()); W("privacy/index.html", privacy()); W("404.html", notFound());
const catalogJson = { generated: "2026-10-15", staging: STAGING, assets: assets.map((a) => ({ asset_id: a.asset_id, slug: a.slug, name: a.name, category: a.category, maturity: a.maturity, asset_type: a.asset_type, one_line_value_proposition: a.one_line_value_proposition, target_buyer: a.target_buyer, price_range: a.valuation_public.range })) };
W("assets.json", JSON.stringify(catalogJson, null, 2) + "\n");

const deckFiles = [];
for (const a of assets) {
  W(`assets/${a.slug}/index.html`, assetPage(a));
  W(`demos/${a.slug}/index.html`, demoPage(a));
  const d = demos[a.slug];
  const pitch = pitchSlides(a, d), short = shortSlides(a, d);
  if (pitch.length < 10 || pitch.length > 12 || short.length < 5 || short.length > 7) throw new Error("deck slide-count contract violated for " + a.slug);
  W(`decks/${a.slug}-pitch.html`, deckHtml(a, pitch, "pitch", { staging: isDraft(a) }));
  W(`decks/${a.slug}-slides.html`, deckHtml(a, short, "slides", { staging: isDraft(a) }));
  W(`decks/${a.slug}-pitch.md`, deckMarkdown(a, pitch, "pitch"));
  W(`decks/${a.slug}-slides.md`, deckMarkdown(a, short, "slides"));
  deckFiles.push(`decks/${a.slug}-pitch`, `decks/${a.slug}-slides`);
}

// Sitemap / robots
const urls = ["/", "/assets/", "/how-acquisition-works/", "/about/", "/inquiry/", "/privacy/", ...assets.filter((a) => !isDraft(a)).flatMap((a) => [`/assets/${a.slug}/`, `/demos/${a.slug}/`])];
W("sitemap.xml", `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${STAGING ? "" : urls.map((u) => `  <url><loc>${SITE}${u}</loc></url>`).join("\n")}\n</urlset>\n`);
W("robots.txt", STAGING ? "User-agent: *\nDisallow: /\n" : `User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: ${SITE}/sitemap.xml\n`);

// PDFs (Chromium headless) — best effort unless --require-pdf
let pdfs = 0;
const chrome = process.env.CHROME_BIN || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
if (!flag("--no-pdf") && fs.existsSync(chrome)) {
  for (const f of deckFiles) {
    const src = path.join(OUT, f + ".html");
    let html = fs.readFileSync(src, "utf8").replace('<script src="/js/deck.js" defer></script>', '<script>document.querySelectorAll(".slide").forEach(function(s){s.hidden=false})</script>');
    const tmp = path.join(OUT, f + ".print.html"); fs.writeFileSync(tmp, html);
    const r = spawnSync(chrome, ["--headless=new", "--no-sandbox", "--disable-gpu", `--print-to-pdf=${path.join(OUT, f + ".pdf")}`, "--no-pdf-header-footer", "file://" + tmp], { timeout: 90000, encoding: "utf8" });
    fs.rmSync(tmp, { force: true });
    if (fs.existsSync(path.join(OUT, f + ".pdf"))) pdfs++; else console.warn("PDF failed:", f, (r.stderr || "").slice(-200));
  }
} else if (!flag("--no-pdf")) console.warn("Chromium not found; PDFs skipped (set CHROME_BIN).");

// Final guard: no forbidden marker may appear in any emitted file.
const bad = [];
(function scan(dir) { for (const e of fs.readdirSync(dir, { withFileTypes: true })) { const p = path.join(dir, e.name); if (e.isDirectory()) scan(p); else if (!/\.(pdf|svg)$/.test(e.name)) { const t = fs.readFileSync(p, "utf8"); for (const m of FORBIDDEN_PUBLIC_MARKERS) if (t.toLowerCase().includes(m.toLowerCase())) bad.push(`${path.relative(OUT, p)}: ${m}`); if (t.includes(CONTACT.phone)) bad.push(`${path.relative(OUT, p)}: phone number`); } } })(OUT);
if (bad.length) { console.error("PUBLIC LEAK GUARD FAILED:\n" + bad.join("\n")); process.exit(1); }

const manifest = [];
(function walk(dir) { for (const e of fs.readdirSync(dir, { withFileTypes: true })) { const p = path.join(dir, e.name); if (e.isDirectory()) walk(p); else manifest.push({ path: path.relative(OUT, p), sha256: crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex"), bytes: fs.statSync(p).size }); } })(OUT);
writeFile(path.join(OUT, "MANIFEST.sha256.json"), JSON.stringify({ staging: STAGING, files: manifest }, null, 2) + "\n");
console.log(`built ${assets.length} asset(s), ${deckFiles.length} decks (${pdfs} PDFs), ${manifest.length} files → ${path.relative(process.cwd(), OUT)} [${STAGING ? "staging" : "production"}]`);
