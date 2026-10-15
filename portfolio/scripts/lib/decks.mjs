import { esc, usd } from "./util.mjs";
import { CONTACT } from "./contact.mjs";

const range = (r) => (r && r[0] != null ? `${usd(r[0])}–${usd(r[1])}` : "on request");
const li = (items) => `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
const excerpt = (demo, n = 16) => (demo?.runs?.[0]?.transcript || "").split("\n").slice(0, n).join("\n");

function packagesTable(a) {
  return `<table><thead><tr><th>Package</th><th>Provisional range</th><th>Rights</th></tr></thead><tbody>${a.acquisition_packages
    .map((p) => `<tr><td>${esc(p.package_name)}</td><td>${esc(p.price_range && p.price_range[0] != null ? range(p.price_range) : "on request")}</td><td>${esc(p.rights_granted)}</td></tr>`).join("")}</tbody></table>`;
}

export function pitchSlides(a, demo) {
  const p = a.public, v = p.valuation_public;
  return [
    { title: a.name, kicker: "Acquisition brief", html: `<p class="big">${esc(p.headline)}</p><p>${esc(a.one_line_value_proposition)}</p><p class="small">Asset ID ${esc(a.asset_id)} · Principal: ${esc(a.creator_attribution)}</p>`,
      notes: `Open with the headline. State plainly that this is a technology asset with no revenue or customers claimed. Asset ID ${a.asset_id}.` },
    { title: "Buyer problem and urgency", html: `<p>${esc(a.buyer_problem)}</p><p class="small"><strong>Cost of inaction.</strong> ${esc(p.cost_of_inaction)}</p>`,
      notes: "Keep this qualitative; no market statistic is cited because none was verified in this build. Ask the buyer how they handle this today." },
    { title: "Target buyer and use case", html: `<h3>Segments</h3>${li(a.target_buyer.segments)}<h3>Roles</h3>${li(a.target_buyer.buyer_roles)}`,
      notes: "Confirm which segment the listener belongs to; adapt the use case to their stack." },
    { title: "Solution overview", html: `<p>${esc(a.solution_summary_public)}</p>`,
      notes: "Describe what exists today, not the roadmap. Anything planned must be labelled as such." },
    { title: "Demo and workflow walkthrough", html: `<p class="small">${esc(p.demo.title)} — <em>${esc(demo?.demo_type || p.demo.type)}: recorded output of the real code on synthetic data.</em></p>${li(p.demo.steps)}<pre>$ ${esc(p.demo.command)}</pre>`,
      notes: `Run or show the recorded transcript. Limitation to state aloud: ${p.demo.limitations}` },
    { title: "Differentiation and alternatives", html: `${li(a.differentiators_public)}<p class="small">Comparison against named competing products was not performed in this build; no superiority claims are made.</p>`,
      notes: "If asked about alternatives, say the comparison has not been done and offer to do it during diligence." },
    { title: "Architecture and integration (public-safe)", html: li(p.architecture_public),
      notes: "Detail beyond this slide is CONFIDENTIAL and requires an NDA." },
    { title: "Evidence", html: `${li(a.verified_capabilities)}<p class="small"><strong>Not claimed:</strong> revenue, customers, usage metrics, production deployment. <strong>Not verified:</strong> ${esc(a.unverified_claims.join(" "))}</p>`,
      notes: "Every item on this slide is backed by a test run or file inspection dated 2026-10-15; offer the evidence index from the diligence package." },
    { title: "Acquisition options and included rights", html: `${packagesTable(a)}<p class="small">Exclusivity is offered only after a rights review. Terms are subject to counsel-reviewed agreements.</p>`,
      notes: "Clarify license vs transfer. Do not imply ownership transfer in a license." },
    { title: "Valuation and comparable-sale rationale", html: `<p class="big">${esc(range(v.range))} <span class="small">source-code transfer, provisional</span></p><p>${esc(v.statement)}</p><p class="small">Basis: ${esc(v.pricing_basis)} · Confidence: ${esc(v.confidence)}. Realized-sale average benchmark: not available for this asset class (comparable sample size 0); treat the range as a starting point for negotiation.</p>`,
      notes: "Be transparent that the number is a replacement-cost-based estimate, not a realized-sale average. Invite the buyer to propose their own anchor." },
    { title: "Diligence, risks and transfer plan", html: `${li(p.diligence_preview)}<p class="small">Transfer: NDA → controlled diligence → agreement → secure delivery of a tagged source snapshot, checksums and documentation → acceptance → handover session.</p>`,
      notes: "Lead with the limitations; credibility comes from naming them first." },
    { title: "Next step", html: `<p class="big">Request acquisition details</p><p>Email <strong>${esc(CONTACT.email)}</strong> or use the inquiry form on the portfolio site, quoting <strong>${esc(a.asset_id)}</strong>.</p><p class="small">© 2026 Daniel Ron Stevens. All Rights Reserved.</p>`,
      notes: "Offer an NDA and a 30-minute technical walkthrough as the concrete next step." },
  ];
}

export function shortSlides(a, demo) {
  const p = a.public, v = p.valuation_public, pk = a.acquisition_packages;
  return [
    { title: a.name, kicker: "PhantomworX + i-Comply · buyer meeting brief", html: `<p class="big">${esc(a.one_line_value_proposition)}</p><p class="small">${esc(a.maturity.replaceAll("_", " "))} · ${esc(a.test_status.replaceAll("_", " "))} · no revenue or customers claimed</p>`,
      notes: "Thirty seconds: what it is, how mature, and that nothing is oversold." },
    { title: "The problem in one slide", html: `<p>${esc(a.buyer_problem)}</p>`, notes: "Ask for the buyer's current approach before continuing." },
    { title: "What you can rely on", html: li(a.verified_capabilities.slice(0, 4)), notes: "These are the evidence-backed items only. Offer the full list in diligence." },
    { title: "Proof: real output", html: `<pre>$ ${esc(p.demo.command)}\n${esc(excerpt(demo))}</pre><p class="small">Recorded run of the real code on synthetic data.</p>`, notes: p.demo.limitations },
    { title: "What you get and what it costs", html: `<p class="big">${esc(range(pk[1]?.price_range))} source transfer · ${esc(range(pk[0]?.price_range))} non-exclusive license</p><p class="small">${esc(v.statement)}</p>`, notes: "Price is provisional and negotiable. Exclusivity is not offered until the rights review completes." },
    { title: "Risks stated up front", html: li(p.public_limitations.slice(0, 4)), notes: "Name every limitation before the buyer finds it." },
    { title: "Next step", html: `<p class="big">NDA → diligence access → offer</p><p>Contact <strong>${esc(CONTACT.email)}</strong> quoting <strong>${esc(a.asset_id)}</strong>.</p>`, notes: "Close by proposing the NDA and a technical walkthrough date." },
  ];
}

const DECK_CSS = `
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#06080c;color:#e8ecf3;font:20px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.stage{display:grid;place-items:center;min-height:100vh;padding:16px}
.slide{width:min(100%,1280px);aspect-ratio:16/9;background:linear-gradient(160deg,#10141b,#0a0c10);border:1px solid #252d3d;border-radius:14px;padding:5% 6%;display:flex;flex-direction:column;position:relative;overflow:hidden}
.slide header{display:flex;justify-content:space-between;font:600 .62em ui-monospace,Menlo,monospace;color:#6ee7d4;letter-spacing:.1em;text-transform:uppercase;margin-bottom:2.4%}
.slide h2{font-size:2em;margin:0 0 3%;line-height:1.15}.slide .body{flex:1;overflow:hidden}.slide ul{margin:0;padding-left:1.1em}.slide li{margin:.35em 0}
.big{font-size:1.5em;font-weight:700;line-height:1.25}.small{font-size:.7em;color:#9aa5b8}pre{background:#06080c;border:1px solid #252d3d;border-radius:10px;padding:14px;font:.62em/1.45 ui-monospace,Menlo,monospace;overflow:hidden;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:.72em}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #252d3d;vertical-align:top}th{color:#9aa5b8}
.slide footer{display:flex;justify-content:space-between;font-size:.55em;color:#6f7b91;margin-top:2%}
.bar{position:fixed;bottom:12px;left:50%;transform:translateX(-50%);display:flex;gap:10px;align-items:center;background:#141923;border:1px solid #252d3d;border-radius:999px;padding:6px 12px;font:.7em ui-monospace,monospace;z-index:9}
.bar button{background:#1a2130;color:#e8ecf3;border:1px solid #252d3d;border-radius:999px;padding:6px 14px;cursor:pointer;font:inherit}
.bar button:focus-visible{outline:3px solid #8b9cff}
.notes-panel{display:none;margin-top:12px;font-size:.7em;color:#9aa5b8}body.notes .notes-panel{display:block}
.draft{position:absolute;left:50%;transform:translateX(-50%);top:2.2%;font:700 .6em ui-monospace,monospace;color:#ffcf70;border:1px solid #ffcf70;border-radius:6px;padding:3px 8px}
@media print{@page{size:1280px 720px;margin:0}body{background:#06080c;-webkit-print-color-adjust:exact;print-color-adjust:exact}.stage{display:block;padding:0}.slide{width:1280px;height:720px;aspect-ratio:auto;border:0;border-radius:0;page-break-after:always;break-after:page;font-size:20px}.bar,.notes-panel{display:none!important}}
`;

export function deckHtml(a, slides, kind, { staging, siteUrl }) {
  const title = `${a.name} — ${kind === "pitch" ? "Pitch deck" : "Meeting slides"}`;
  const body = slides.map((s, i) => `<section class="slide" aria-label="Slide ${i + 1} of ${slides.length}"${i ? " hidden" : ""}>
<header><span>PhantomworX + i-Comply</span><span>${esc(s.kicker || a.asset_id)}</span></header>
<h2>${esc(s.title)}</h2><div class="body">${s.html}</div>
${staging ? '<span class="draft">DRAFT · pending owner approval</span>' : ""}
<footer><span>© 2026 Daniel Ron Stevens. All Rights Reserved.</span><span>${i + 1} / ${slides.length}</span></footer>
<aside class="notes-panel"><strong>Speaker notes:</strong> ${esc(s.notes)}</aside></section>`).join("\n");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
${staging ? '<meta name="robots" content="noindex,nofollow">' : ""}<style>${DECK_CSS}</style></head><body><div class="stage" role="region" aria-label="${esc(title)}">${body}</div>
<nav class="bar" aria-label="Slide controls"><button id="prev" type="button">Prev</button><span id="pos" aria-live="polite">1</span><button id="next" type="button">Next</button><span class="small">N: notes</span></nav>
<script src="/js/deck.js" defer></script></body></html>`;
}

export function deckMarkdown(a, slides, kind) {
  return `# ${a.name} — ${kind === "pitch" ? "Pitch deck" : "Meeting slides"}\n\nPhantomworX + i-Comply · © 2026 Daniel Ron Stevens. All Rights Reserved.\n\n` +
    slides.map((s, i) => `## ${i + 1}. ${s.title}\n\n${s.html.replace(/<li>/g, "- ").replace(/<\/li>/g, "\n").replace(/<br\s*\/?>/g, "\n").replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\n{3,}/g, "\n\n").trim()}\n\n*Notes:* ${s.notes}\n`).join("\n");
}
