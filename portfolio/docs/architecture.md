# Architecture

```
curation (private)  ──► build-register ──► private/assets/*.json   (full records, schema-validated)
source clones (ro)  ──►                └─► data/assets/*.public.json (whitelist projection, PURSUE only)
source clones (ro)  ──► record-demos  ──► data/demos/*.json         (sanitized real-run transcripts, synthetic inputs)
data/*              ──► build-site    ──► dist/  (HTML, decks .html/.md/.pdf, demos, assets.json, sitemap, robots)
private/assets      ──► build-diligence ► private/diligence/<slug>/  (never copied to dist)
dist/               ──► src/server.mjs ──► HTTP (+ /api/inquiry, /api/event, /healthz)
```

## Decisions
- **Zero-dependency Node** static generator and server: small attack surface, reproducible, no lockfile drift. Python is used only for the source inventory (`scripts/inventory/inventory.py`).
- **Whitelist projection** (`scripts/lib/tiers.mjs`) instead of field stripping, so new private fields can never leak by omission.
- **Publication gate** (`publication.approved`) with a production build that refuses to run without an `https://` `PWX_SITE_URL`.
- **Recorded demos** of the real code on synthetic data rather than simulated UIs; each demo declares its type (`RECORDED_RUN`), expected strings and limitations, and a test checks the transcript.
- **Provisional valuation** from an explicit replacement-cost model (`scripts/lib/valuation.mjs`) because no verified realized-sale comparable exists for pre-revenue code assets. Every assumption is written into the record.
- **Inquiry storage** is an append-only owner-only JSONL file (fsync'd). No email is sent; delivery to the owner's inbox is not implemented (untestable without credentials).
- **Private diligence area** is **not implemented**: the handoff allows it only if securely implemented (authentication, NDA workflow, audit log, expiring links). Diligence material is generated as files under `private/` and shared out-of-band after an NDA.

## Server controls
CSP (`script-src 'self'`), frame-ancestors none, nosniff, no-referrer, permissions policy, optional HSTS (`PWX_BEHIND_TLS=1`), request timeouts, 16 KB inquiry body cap, content-type enforcement, honeypot, per-address in-memory rate limits (`PWX_TRUST_PROXY=1` to use `X-Forwarded-For`), path-traversal and dotfile blocking, `MANIFEST.sha256.json` and non-dist paths unreachable, logs contain no personal data.

## Asset graph
Relationships (`OVERLAPS_WITH`, `CONTAINS`, `INTEGRATES_WITH`) are stored in each record and checked for dangling targets by `npm run validate`. Stable IDs `PWX-ASSET-000001…`.
