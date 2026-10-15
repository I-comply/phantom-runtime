# Deployment guide

**Nothing has been deployed.** Domain purchase, hosting, and paid services require the owner's explicit authorization.

## Prerequisites
- Node ≥ 20 on the host; a TLS-terminating reverse proxy (Caddy, nginx, a platform load balancer) in front; a domain.
- Owner approval: at least one asset with `publication.approved: true`.

## Build (on a trusted machine with the curation data)
```bash
cd portfolio
npm run register && npm run validate && npm test
PWX_SITE_URL=https://your-domain npm run build      # production: approved assets only; PDFs need Chromium (CHROME_BIN)
```
Deployable artifact = `dist/` + `src/server.mjs` (+ `package.json`). No `private/` content is needed on the server.

## Run
```bash
cd portfolio
cp .env.example .env   # names only; export the values in your process manager
PORT=8080 HOST=127.0.0.1 PWX_TRUST_PROXY=1 PWX_BEHIND_TLS=1 \
PWX_INQUIRY_FILE=/var/lib/pwx/inquiries.jsonl PWX_METRICS_FILE=/var/lib/pwx/metrics.json \
node src/server.mjs
```
Create `/var/lib/pwx` owned by the service user with mode 0700. A `Dockerfile` is provided (`docker build -f portfolio/Dockerfile -t pwx-portfolio portfolio`); it was **not built or run** in this environment (no Docker daemon).

## Reading inquiries
`node scripts/list-inquiries.mjs /var/lib/pwx/inquiries.jsonl` (prints reference, time, asset, interest and contact). The file contains personal data: restrict access and delete on request (see PRIVACY.md).

## Smoke tests (after every deploy)
```bash
BASE=https://your-domain bash scripts/smoke.sh
```
Checks `/healthz`, home, catalog, one asset page, a deck, `robots.txt`, `sitemap.xml`, that `/private/` and traversal paths return 404, security headers, and that an invalid inquiry returns 422 (no inquiry is stored by the smoke test).

## First-publication checklist
- [ ] `publication.approved` set deliberately per asset; staging copy reviewed.
- [ ] Counsel review of ownership/AI-authorship (see private/docs/IP-and-rights-review.md).
- [ ] Secret scan on full history of source repos; dependency/license review.
- [ ] Inquiry notification path chosen and tested end to end with a real message to the owner.
- [ ] `PWX_SITE_URL` is the final https origin; sitemap/robots verified.
