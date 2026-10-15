# PhantomworX + i-Comply — buyer-conversion portfolio

Static storefront, per-asset buyer packages (page, 10–12 slide pitch deck, 5–7 slide meeting deck, recorded demo, private diligence package) and a small inquiry service. Zero runtime dependencies (Node ≥ 20 for the site; Python 3 only to re-record demos and the source inventory).

Brand: PhantomworX + i-Comply · Principal: Daniel Ron Stevens · © 2026 Daniel Ron Stevens. All Rights Reserved.

## Three information tiers

| Tier | Where | In git? |
|---|---|---|
| PUBLIC | `data/assets/*.public.json`, `data/demos/*.json`, generated `dist/` | yes (public projection only) |
| CONFIDENTIAL / NDA | `private/diligence/<slug>/`, `private/research/`, `private/docs/` | **no** (gitignored) |
| RESTRICTED | secrets — never stored | n/a |

`scripts/lib/tiers.mjs` projects a full record to the public tier with a **whitelist** (deny by default). The build refuses to emit a file containing a forbidden marker or the owner's phone number.

## Commands

```bash
cd portfolio
npm run register        # curation → validated records (private/assets) + public projection (data/assets)
npm run demos           # re-record demo transcripts from the source trees (needs /home/user/src clones; PWX_SRC_ROOT overrides)
npm run validate        # schema + cross-checks
npm run build:staging   # dist/ with all assets, DRAFT banners, noindex, PDFs (Chromium; CHROME_BIN overrides)
npm test                # 30 tests: schema, leak, accessibility, links, SEO, decks, server, inquiry
PWX_SITE_URL=https://your-domain npm run build   # production: only publication.approved assets
PORT=8080 npm run serve # serves dist/ + /api/inquiry, /api/event, /healthz
node scripts/build-diligence.mjs                 # private diligence packages (after a build)
```

The curation input (`private/curation/assets.mjs`) and the source clones are required only to regenerate records. A fresh checkout can build and test the site from the committed public data.

## Publication gate

Every asset has `publication.approved: false`. A production build (`npm run build`) publishes **nothing** until the owner sets it to `true` and re-runs `npm run register`. Staging builds show every asset with a visible DRAFT banner.

## Layout
`schemas/` JSON Schema · `scripts/` register, site, demos, diligence, validation · `src/server.mjs` server · `public/` css/js/brand · `data/` public data · `demo-fixtures/` synthetic inputs · `tests/` · `docs/` · `private/` (ignored).

See `docs/architecture.md`, `docs/deployment.md`, `docs/rollback.md`, `docs/acceptance-report.md`, `SECURITY.md`, `PRIVACY.md`, `LICENSES-AND-ATTRIBUTION.md`.
