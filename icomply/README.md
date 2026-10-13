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
- Each target has a check interval (hourly/6h/daily); cron only runs targets that are due. Run history at `/dashboard/sites/<id>` shows added/removed text per change.
- robots.txt is honored (UA `icomply-sentinel`; 5xx/unreachable robots = skip). Disable only with `ICOMPLY_RESPECT_ROBOTS=false` when permitted.
- 5 consecutive failures set a target to `ERROR` (excluded from cron) and send a `site_error` webhook; Resume re-enables it.

## Webhook verification
Events: `change`, `site_error`. Headers: `X-iComply-Timestamp`, `X-iComply-Signature: sha256=HMAC_SHA256(secret, "<timestamp>.<raw body>")`. Reject if timestamp skew > 300s. Reference: `app/api/webhooks/route.ts`.

## Security
- SSRF guard on scrape and webhook targets: http(s) only, no credentials, private/loopback/link-local/metadata ranges blocked at connect time (DNS-rebinding safe), redirects re-validated (max 3), 5 MB response cap.
- Webhook secrets are AES-256-GCM encrypted at rest (`ICOMPLY_ENCRYPTION_KEY`); losing the key requires re-entering secrets.
- Respect each municipality's robots.txt/terms; cadence is operator-controlled.

## Test
`npm test` (unit; integration runs when `DATABASE_URL` points at a migrated Postgres), `npm run typecheck`.
