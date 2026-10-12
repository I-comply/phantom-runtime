# iComply

Municipal ordinance change monitor: Cheerio scraper → SHA-256 change detection → signed webhooks. Next.js 14 + Prisma + Postgres.

## Setup
```
cp .env.example .env   # fill values
npm ci && npx prisma migrate deploy
npm run dev            # or: npm run build && npm start, or docker build .
```

## Operation
- `/dashboard` (HTTP Basic: `DASHBOARD_USER`/`DASHBOARD_PASSWORD`; fails closed in production if unset): add targets, run now, pause/resume, delete.
- `/dashboard/webhooks`: register endpoints + signing secrets.
- `GET /api/cron/scrape` with `Authorization: Bearer $CRON_SECRET` scrapes all ACTIVE targets (3 concurrent). `vercel.json` schedules it every 6h; elsewhere call it from any scheduler.
- `GET /api/health`: DB liveness.
- First scrape of a target records a baseline (no webhook). Later changes log a diff summary and notify all active endpoints (3 attempts, exponential backoff; each result stored in `WebhookDelivery`).
- 5 consecutive failures set a target to `ERROR` (excluded from cron); Resume re-enables it.

## Webhook verification
Headers: `X-iComply-Timestamp`, `X-iComply-Signature: sha256=HMAC_SHA256(secret, "<timestamp>.<raw body>")`. Reject if timestamp skew > 300s. Reference: `app/api/webhooks/route.ts`.

## Security
- SSRF guard on scrape and webhook targets: http(s) only, no credentials, private/loopback/link-local/metadata ranges blocked at connect time (DNS-rebinding safe), redirects re-validated (max 3), 5 MB response cap.
- Webhook secrets are stored in plaintext (required for HMAC); restrict DB access accordingly.
- Respect each municipality's robots.txt/terms; cadence is operator-controlled.

## Test
`npm test` (unit), `npm run typecheck`.
