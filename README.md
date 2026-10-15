# phantom-runtime

Monorepo for the Phantom runtime: a deterministic, event-sourced runtime (state is rebuilt by replaying immutable events), plus supporting tools, database migrations and a separate Next.js service. Each part has its own README with detail; this file is an index.

## Layout

| Path | Contents |
|---|---|
| `phantom-runtime-main/` | Main application: FastAPI + SQLAlchemy backend (`backend/`), React/Vite frontend (`frontend/`), PostgreSQL event store, `docker-compose.yml`. |
| `icomply/` | iComply: Next.js 14 + Prisma + Postgres municipal ordinance change monitor (scraper, change detection, signed webhooks). |
| `replaycheck/` | Python (stdlib only) tool that checks `state == fold(events)` for an event-sourced system; includes an adapter for the PhantomOS reconstructor. |
| `temporal-kernel/` | Python (stdlib only) workflow orchestration node over an append-only, hash-chained SQLite event log. |
| `supabase/` | SQL migrations, seeds, rollout scripts and security tests for the Supabase/PostgreSQL schema (events, workspaces, API keys, RLS). |
| `ctal/` | CTAL (Continuous Trust and Assurance Ledger) P0: AQPD/CLES contracts, signed assurance envelope, tenant-scoped hash-chained ledger, signed export and offline verifier. Python + `cryptography`. See `docs/ctal/README.md`. |
| `portfolio/` | PhantomworX + i-Comply buyer-conversion portfolio: validated asset records, static storefront, per-asset decks and recorded demos, inquiry service. See `portfolio/README.md`. |
| `observability/` | `observability.py`: Prometheus metrics, tracing and structured logging module. |
| `docs/` | Earlier reports and guides (execution, testing, Supabase). See `docs/README.md`. |
| `tests/` | `test_suite.py` (see its header note on scope) and `load-tests-k6.js` (k6 load scenarios). |
| `.github/workflows/` | CI for `phantom-runtime-main`, `icomply`, `replaycheck`, `supabase` and `temporal-kernel`. |

Top-level files: `DEPLOY.md` (Render deployment), `render.yaml` (Render blueprint), `docker-compose.monitoring.yml` (Prometheus/Grafana stack; it mounts config files from `observability/` that are not all present in this repo, so check before use), `supabase-demo.ts` and `supabase-backend-demo.py` (Supabase demos), `LICENSE`.

## Run and test

### phantom-runtime-main
```bash
cd phantom-runtime-main
docker-compose up -d                      # PostgreSQL + backend

# or locally
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
cd ../frontend && yarn install && yarn dev
```
Backend tests are in `phantom-runtime-main/backend/tests/` (pytest, needs a PostgreSQL via `DATABASE_URL`; see `.github/workflows/phantom-runtime-main.yml` for the CI setup).

### icomply
```bash
cd icomply
cp .env.example .env                      # fill values
npm ci && npx prisma migrate deploy
npm run dev
npm test                                  # vitest
npm run typecheck
```

### replaycheck
```bash
cd replaycheck && ./verify.sh
```

### temporal-kernel
```bash
cd temporal-kernel && ./verify.sh         # tests + demo
python3 -m tkernel demo
```

### supabase
```bash
PGHOST=localhost PGUSER=postgres PGPASSWORD=... supabase/tests/run.sh
```
Needs a PostgreSQL where a scratch database can be created. See `supabase/README.md` and `supabase/ROLLOUT.md`.

## Deployment

See `DEPLOY.md` (Render, using `render.yaml`).

## License

Proprietary. All rights reserved; see `LICENSE`.


---

© 2026 Daniel Ron Stevens. All Rights Reserved.
PhantomWorks™️
