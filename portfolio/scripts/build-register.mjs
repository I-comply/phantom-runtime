#!/usr/bin/env node
// Expands curation input into schema-validated asset records.
//   private/assets/PWX-ASSET-xxxxxx.json   full record (PRIVATE tier, gitignored)
//   data/assets/PWX-ASSET-xxxxxx.public.json   public-tier projection (PURSUE assets only)
//   private/register/disposition-register.{json,md}
// Usage: node scripts/build-register.mjs [--curation FILE]
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, readJson, writeFile, usd } from "./lib/util.mjs";
import { validate } from "./lib/schema.mjs";
import { priceBands, MODEL } from "./lib/valuation.mjs";
import { toPublic } from "./lib/tiers.mjs";

const args = process.argv.slice(2);
const curFile = args.includes("--curation") ? args[args.indexOf("--curation") + 1] : path.join(ROOT, "private/curation/assets.mjs");
const SRC_ROOT = process.env.PWX_SRC_ROOT || "/home/user/src";
const REPO_ROOT = path.resolve(ROOT, "..");
const TODAY = "2026-10-15";
const schema = readJson(path.join(ROOT, "schemas/asset.schema.json"));

const CODE_EXT = new Set([".py", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".sh", ".sql"]);
const TEST_RE = /(^|\/)(tests?|__tests__)\/|(^|\/)test_[^/]+\.py$|\.(test|spec)\.[jt]sx?$|_test\.py$/;

function rootDir(r) { return r === "phantom-runtime" ? REPO_ROOT : path.join(SRC_ROOT, r); }

function measure(components) {
  let srcLoc = 0, testLoc = 0, files = 0;
  for (const c of components) {
    const base = rootDir(c.root);
    const list = execFileSync("git", ["-C", base, "ls-files", c.path === "." ? "." : c.path], { encoding: "utf8" }).split("\n").filter(Boolean);
    for (const f of list) {
      if (!CODE_EXT.has(path.extname(f))) continue;
      let txt; try { txt = fs.readFileSync(path.join(base, f), "utf8"); } catch { continue; }
      const n = txt.split("\n").length;
      files++;
      if (TEST_RE.test(f)) testLoc += n; else srcLoc += n;
    }
  }
  return { srcLoc, testLoc, files };
}

const id = (n) => `PWX-ASSET-${String(n).padStart(6, "0")}`;
const MARKET_URLS = [
  "https://blog.acquire.com/acquire-com-biannual-acquisition-multiples-report-jan-2026/",
  "https://blog.acquire.com/saas-valuation-multiples/",
  "https://landing.flippa.com/pages/insights-h1-2026/",
  "https://flippa.com/lps/closed-deals/",
];
const COMMON_BLOCKERS = [
  "Counsel review of ownership and of AI-assisted authorship is outstanding.",
  "Third-party dependency license review is outstanding (SBOM provided in the diligence package).",
  "Owner approval of publication scope (publication.approved is false).",
  "Secret scan covered the working tree only; full-history scan was not possible on shallow clones of private repositories.",
];

const mod = await import(pathToFileURL(path.resolve(curFile)).href);
const { assets, register, missingLeads, faq, BASE_RESTRICTIONS, PRICE_STATEMENT } = mod;

fs.mkdirSync(path.join(ROOT, "private/assets"), { recursive: true });
fs.mkdirSync(path.join(ROOT, "data/assets"), { recursive: true });
const records = [];
let failed = false;

for (const a of assets) {
  const loc = measure(a.components);
  const b = priceBands(loc);
  const pkgNames = "non-exclusive source license; asset-only source-code transfer; exclusive rights (subject to rights review)";
  const packages = [
    { package_name: "Non-exclusive source license", package_type: "LICENSE_NON_EXCLUSIVE", price: b.license.price, price_range: b.license.range,
      rights_granted: "Defined internal-use rights to the listed source and documentation; no ownership transfer; seller keeps the right to license others.",
      exclusions: ["Ownership", "Exclusivity", "Shared components not listed in the agreement", "Trademarks and brand names"],
      support_period: "30 days of clarification support after delivery", transfer_deliverables: ["Source snapshot at a named commit", "Build/run/test instructions", "Dependency and license inventory"], availability: "Available after NDA and rights review." },
    { package_name: "Asset-only source-code transfer", package_type: "SOURCE_TRANSFER", price: b.source_transfer.price, price_range: b.source_transfer.range,
      rights_granted: "Assignment of the seller's rights in the enumerated source files, subject to third-party licenses and counsel-reviewed terms.",
      exclusions: ["Unrelated shared components", "Third-party code and its licenses", "Customer data (none exists)", "Any operating business"],
      support_period: "60 days of handover support after delivery", transfer_deliverables: ["Source snapshot and tagged commit", "Documentation and test evidence", "Checksums manifest", "Handover session"], availability: "Available after NDA, diligence and rights review." },
    { package_name: "Exclusive rights", package_type: "EXCLUSIVE_RIGHTS", price: null,
      rights_granted: "Exclusive rights, only if the rights review confirms exclusivity is supportable.",
      exclusions: ["Anything the rights review cannot confirm"], support_period: "To be agreed", transfer_deliverables: ["As for source-code transfer"], availability: "Priced on request; not offered until ownership and third-party license review is complete." },
  ];
  const valuationPublic = {
    pricing_basis: "PROVISIONAL_ESTIMATE", confidence: "LOW",
    range: b.source_transfer.range, license_range: b.license.range,
    statement: PRICE_STATEMENT("LOW"),
  };
  const rec = {
    asset_id: id(a.n), slug: a.slug, name: a.name, brand: "PhantomworX + i-Comply", creator_attribution: "Daniel Ron Stevens",
    disposition: a.disposition, disposition_rationale: a.disposition_rationale, asset_type: a.asset_type, category: a.category,
    one_line_value_proposition: a.one_line, buyer_problem: a.buyer_problem,
    target_buyer: { segments: a.segments, buyer_roles: a.roles, urgency_evidence: [] },
    solution_summary_public: a.solution, differentiators_public: a.differentiators,
    verified_capabilities: a.capabilities, unverified_claims: a.unverified,
    maturity: a.maturity, deployment_status: a.deployment, test_status: a.test_status,
    revenue_status: "NONE_VERIFIED", traction_status: "NONE_VERIFIED",
    source_provenance: a.provenance.map((p) => ({ source_id: p.source_id, locator: p.locator, commit_sha_or_export_id: p.sha, evidence_paths: p.paths, last_verified: TODAY })),
    relationships: a.relationships,
    ownership: {
      status: "ATTRIBUTED_PENDING_REVIEW",
      contributors: [{ name: "Daniel Ron Stevens", basis: "Copyright notice in LICENSE/README footers; GitHub account PhantomworX" }, { name: "AI coding assistants (author 'Claude', 'Wraith_AI')", basis: "Git commit authorship in phantom-runtime history; share of authorship not quantified" }],
      third_party_components: a.third_party, licenses: a.licenses, transfer_restrictions: BASE_RESTRICTIONS,
    },
    ip_classification: "CONFIDENTIAL_UNTIL_REVIEW", security_review_status: a.security,
    market_validation: { date_checked: TODAY, buyer_pain_sources: [], competing_products: [], comparable_closed_sales: [],
      comparability_notes: "No verified realized-sale comparables for pre-revenue source-code assets were obtainable: direct fetches of Flippa/Acquire.com pages were blocked in the build environment and web-search summaries surfaced only asking prices and revenue-bearing business sales. Buyer-pain and competitor research is not completed; no market statistic is cited publicly." },
    valuation: {
      method: `Replacement-cost model v${MODEL.version} with an assumed realization band (provisional; not a realized-sale average)`,
      currency: "USD", realized_comparable_median: null, realized_comparable_mean: null, sample_size: 0, confidence: "LOW",
      recommended_exit_price: b.source_transfer.price, recommended_price_range: b.source_transfer.range, pricing_basis: "PROVISIONAL_ESTIMATE",
      assumptions: [
        `Measured code: ${loc.srcLoc} source LOC and ${loc.testLoc} test LOC across ${loc.files} code files (2026-10-15 working tree).`,
        `Effort = (source LOC + ${MODEL.test_loc_weight} × test LOC) / ${MODEL.loc_per_person_week} LOC per person-week = ${b.person_weeks} person-weeks (assumption).`,
        `Replacement cost = person-weeks × $${MODEL.rate_per_person_week_usd}/person-week = ${usd(b.replacement_cost)} (assumed blended rate).`,
        `Realization band ${MODEL.realization_band[0] * 100}%–${MODEL.realization_band[1] * 100}% of replacement cost for a pre-revenue, zero-traction asset (unvalidated assumption).`,
        `Non-exclusive license priced at ${MODEL.license_fraction[0] * 100}%–${MODEL.license_fraction[1] * 100}% of the source-transfer range.`,
        "Lines of code and test counts are inputs to a cost model only; they are not evidence of market value.",
      ],
      exclusions: ["No realized-sale comparable used", "Excludes exclusivity premium", "Excludes shared-component rights", "Excludes support beyond the stated period", "Excludes any business, revenue or customer value (none verified)"],
      source_urls: MARKET_URLS,
    },
    acquisition_packages: packages,
    buyer_assets: {
      public_page: `assets/${a.slug}/`, pitch_deck: `decks/${a.slug}-pitch.html`, slide_deck: `decks/${a.slug}-slides.html`,
      demo: `demos/${a.slug}/`, demo_type: a.demo.type, listing_copy: `assets/${a.slug}/`,
      diligence_index: `private/diligence/${a.slug}/INDEX.md`, handover_plan: `private/diligence/${a.slug}/HANDOVER.md`,
    },
    contact_cta: "Request acquisition details",
    status: "PACKAGED", blockers: COMMON_BLOCKERS, next_actions: ["Owner reviews public copy and approves or edits publication scope.", "Counsel reviews ownership, AI-authorship and license position.", "Run full-history secret scan on original (non-shallow) clones."],
    last_reviewed: TODAY,
    publication: { approved: false, approved_by: null, approved_on: null },
    public: {
      headline: a.headline, subheadline: a.subheadline, cost_of_inaction: a.cost_of_inaction,
      public_limitations: a.limitations, architecture_public: a.architecture,
      risk_summary: a.risksAnswer, valuation_public: valuationPublic,
      faq: faq({ pkgNames, statusAnswer: a.statusAnswer, depsAnswer: a.deps, risksAnswer: a.risksAnswer }),
      demo: { title: a.demo.title, type: a.demo.type, command: a.demo.command, steps: a.demo.steps, limitations: a.demo.limitations, expect: a.demo.expect },
      diligence_preview: [
        "Tests: " + a.statusAnswer,
        "Dependencies: " + a.deps,
        "License: " + a.licenses.map((l) => l.license).join("; "),
        "Security posture: automated secret and pattern scan only; no manual security review yet.",
        "Known limitations: " + a.limitations.join(" "),
      ],
      stats: { src_loc: loc.srcLoc, test_loc: loc.testLoc },
    },
  };
  const errs = validate(schema, rec);
  if (errs.length) { failed = true; console.error(`INVALID ${rec.asset_id}:\n  ` + errs.join("\n  ")); }
  records.push(rec);
  writeFile(path.join(ROOT, "private/assets", `${rec.asset_id}.json`), JSON.stringify(rec, null, 2) + "\n");
  writeFile(path.join(ROOT, "data/assets", `${rec.asset_id}.public.json`), JSON.stringify(toPublic(rec), null, 2) + "\n");
}

for (const r of register) {
  const prov = [{ source_id: r.source, locator: r.source === "phantom-runtime" ? PWR_URL() : `https://github.com/I-comply/${r.source}`, commit_sha_or_export_id: r.sha, evidence_paths: r.paths || [], last_verified: TODAY },
    ...(r.extraSources || []).map((e) => ({ source_id: e.id, locator: `https://github.com/I-comply/${e.id}`, commit_sha_or_export_id: e.sha, evidence_paths: ["README.md"], last_verified: TODAY }))];
  const rec = {
    asset_id: id(r.n), slug: r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60), name: r.name,
    brand: "PhantomworX + i-Comply", creator_attribution: "Daniel Ron Stevens", disposition: r.disposition, disposition_rationale: r.rationale,
    asset_type: r.asset_type, category: r.category, one_line_value_proposition: r.rationale.split(". ")[0] + ".",
    buyer_problem: "", target_buyer: { segments: [], buyer_roles: [], urgency_evidence: [] }, solution_summary_public: "", differentiators_public: [],
    verified_capabilities: [], unverified_claims: ["All capabilities unverified beyond file inspection."], maturity: r.maturity,
    deployment_status: "UNVERIFIED", test_status: r.tests || "UNVERIFIED", revenue_status: "NONE_VERIFIED", traction_status: "NONE_VERIFIED",
    source_provenance: prov, relationships: r.rel || [],
    ownership: { status: "UNVERIFIED", contributors: [], third_party_components: [], licenses: [], transfer_restrictions: BASE_RESTRICTIONS },
    ip_classification: "CONFIDENTIAL_UNTIL_REVIEW", security_review_status: "NOT_STARTED",
    market_validation: { date_checked: TODAY, buyer_pain_sources: [], competing_products: [], comparable_closed_sales: [], comparability_notes: "Not researched: asset is not being marketed." },
    valuation: { method: "Not priced", currency: "USD", realized_comparable_median: null, realized_comparable_mean: null, sample_size: 0, confidence: "LOW", recommended_exit_price: null, recommended_price_range: [null, null], pricing_basis: "NOT_PRICED", assumptions: [], exclusions: ["Not priced: disposition is not PURSUE"], source_urls: [] },
    acquisition_packages: [],
    buyer_assets: { public_page: "", pitch_deck: "", slide_deck: "", demo: "", demo_type: "NOT_CREATED", listing_copy: "", diligence_index: "", handover_plan: "" },
    contact_cta: "Request acquisition details", status: "DISCOVERY", blockers: ["Not approved for pursuit."], next_actions: [], last_reviewed: TODAY,
    publication: { approved: false, approved_by: null, approved_on: null },
  };
  const errs = validate(schema, rec);
  if (errs.length) { failed = true; console.error(`INVALID ${rec.asset_id}:\n  ` + errs.join("\n  ")); }
  records.push(rec);
  writeFile(path.join(ROOT, "private/assets", `${rec.asset_id}.json`), JSON.stringify(rec, null, 2) + "\n");
}
function PWR_URL() { return "https://github.com/I-comply/phantom-runtime"; }

// Disposition register
const rows = records.map((r) => ({ asset_id: r.asset_id, name: r.name, disposition: r.disposition, maturity: r.maturity, test_status: r.test_status, price_range: r.valuation.recommended_price_range, rationale: r.disposition_rationale, relationships: (r.relationships || []).map((x) => `${x.type} ${x.target}`) }));
writeFile(path.join(ROOT, "private/register/disposition-register.json"), JSON.stringify({ generated: TODAY, rows, missing_leads: missingLeads }, null, 2) + "\n");
const md = ["# Asset disposition register", "", `Generated ${TODAY}. PRIVATE tier. Prices are provisional (confidence LOW; realized-comparable sample size 0).`, "",
  "| ID | Asset | Disposition | Maturity | Tests | Provisional source-transfer range (USD) | Rationale |", "|---|---|---|---|---|---|---|",
  ...rows.map((r) => `| ${r.asset_id} | ${r.name} | **${r.disposition}** | ${r.maturity} | ${r.test_status} | ${r.price_range[0] == null ? "—" : usd(r.price_range[0]) + "–" + usd(r.price_range[1])} | ${r.rationale.replace(/\|/g, "/")} |`),
  "", "## Asset leads from the handoff that could not be verified", "", ...missingLeads.map((m) => `- **${m.lead}** — ${m.result}`), ""].join("\n");
writeFile(path.join(ROOT, "private/register/disposition-register.md"), md);
console.log(`${records.length} records (${assets.length} PURSUE) ${failed ? "WITH ERRORS" : "valid"}`);
process.exit(failed ? 1 : 0);
