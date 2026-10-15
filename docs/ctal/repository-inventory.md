# Repository inventory

Reviewed: `I-comply/phantom-runtime`, branch `ccr-fd981673-pt8zx2`, base commit `734db279ef18c69715e6f9d265e077d4ad1be688`, working tree clean at start (265 tracked files). Implementation added under `ctal/`, `docs/ctal/`, `.github/workflows/ctal.yml`, and 4 lines in `.gitignore`. No existing file was modified other than `.gitignore`.

## Existing components (unchanged)
| Path | Stack | Notes |
|---|---|---|
| `phantom-runtime-main/` | FastAPI + SQLAlchemy backend, React/Vite frontend, PostgreSQL | tests need PostgreSQL (`DATABASE_URL`) |
| `icomply/` | Next.js 14 + Prisma + Postgres | `npm test` (vitest) |
| `replaycheck/` | Python stdlib | `./verify.sh` |
| `temporal-kernel/` | Python stdlib, SQLite hash-chained event log | `./verify.sh` |
| `supabase/` | SQL migrations/RLS/tests | needs PostgreSQL |
| `observability/`, `render.yaml`, `DEPLOY.md`, `.github/workflows/*` | Prometheus/OTel-style module, Render blueprint, CI | |

## Search results for required assets (search terms, not proof)
| Term | Result |
|---|---|
| AQPD / Adversarial Quality Poisoning Defense | **Not found** (working tree, `git grep` over the last 50 commits, `I-comply/agent-trust-layer`) |
| CLES / Cryptographic Licensing and Entitlement System / "entitlement" | **Not found** (only unrelated `.gitignore` text matched the pattern) |
| Auditable Adaptive State Protocol, S0–S1–S2, L0–L8, AT-01..07 | **Not found** |
| canonical JSON, SHA-256 hash chain | Found in `temporal-kernel` (`hash = sha256(canon(event incl. prev_hash))`, SQLite triggers reject UPDATE/DELETE; optional HMAC) — design precedent, not reused as code |
| Ed25519 / envelope / signed export | Not found |
| Auth/tenancy | `supabase/` has workspaces + API keys + RLS (Postgres); not reused (CTAL uses SQLite in this P0) |

## Baseline (before any change; Python 3.13.16, Linux)
| Command | Result |
|---|---|
| `cd temporal-kernel && ./verify.sh` | PROVEN: 19 tests OK |
| `cd replaycheck && ./verify.sh` | PROVEN: 21 tests OK |
| `phantom-runtime-main` backend pytest | UNTESTED (no PostgreSQL, pytest not installed) |
| `icomply` `npm test` / typecheck | UNTESTED (not run; out of CTAL scope) |
| `supabase/tests/run.sh` | UNTESTED (no PostgreSQL) |
