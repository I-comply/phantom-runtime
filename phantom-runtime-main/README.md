# PhantomOS Runtime Reconstitution Engine

A deterministic event-sourced runtime system that reconstructs application state from immutable event logs.

## Architecture

- **Backend**: FastAPI with SQLAlchemy ORM
- **Database**: PostgreSQL (event store)
- **Frontend**: React (Vite)
- **Deployment**: Docker Compose

## Core Concepts

### Event Sourcing
All state changes are stored as immutable events. Entity state is reconstructed by replaying events in chronological order.

### Stateless Runtime
No cached state - every request rebuilds state from the event log, ensuring consistency and auditability.

### Multi-Entity Support
Isolated state management for multiple entities with independent event streams.

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Start all services (PostgreSQL + Backend)
docker-compose up -d

# Check logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

### Local Development

#### Backend
```bash
cd backend
pip install -r requirements.txt

# Set up PostgreSQL locally or use Docker:
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=phantomos postgres:15-alpine

# Run server
uvicorn app.main:app --reload --port 8001
```

#### Frontend
```bash
cd frontend
yarn install
yarn dev
```

## API Endpoints

### Events
- `POST /api/events/` - Append new event
- `GET /api/events/entity/{entity_id}` - Get all events for entity
- `GET /api/events/` - Get recent events (all entities)

### State
- `GET /api/state/{entity_id}` - Reconstruct entity state
- `GET /api/state/` - List all entities
- `POST /api/state/agent/run` - Execute ephemeral agent operation

### Health
- `GET /api/health` - Health check

## Event Types

- `init` - Initialize entity with initial state
- `update` - Update specific fields
- `compute` - Store computed results
- `reset` - Clear entity state
- `delete_field` - Remove specific field

## Example Usage

### Create Entity
```bash
curl -X POST http://localhost:8001/api/events/ \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "user_123",
    "event_type": "init",
    "payload": {"name": "Alice", "balance": 100}
  }'
```

### Update State
```bash
curl -X POST http://localhost:8001/api/events/ \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "user_123",
    "event_type": "update",
    "payload": {"balance": 150}
  }'
```

### Reconstruct State
```bash
curl http://localhost:8001/api/state/user_123
```

Response:
```json
{
  "entity_id": "user_123",
  "state": {
    "name": "Alice",
    "balance": 150
  },
  "event_count": 2,
  "runtime_status": "active"
}
```

## Environment Variables

### Backend (.env)
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/phantomos
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
# One-time: set this to mint the first admin API key (POST /api/v3/security/api-keys
# with header X-Bootstrap-Key), then unset it. Every other write/execute endpoint
# requires a real API key (X-API-Key) with the matching RBAC permission.
PHANTOM_BOOTSTRAP_ADMIN_KEY=
```
`CORS_ORIGINS` must be an explicit origin list, not `*` — the app refuses to start
with a wildcard because `allow_credentials=True` is already set and the two
together are a known CORS misconfiguration (and this API has no cookie-based auth
for credentialed CORS to protect in the first place).

## Auth

Every write/execute endpoint and every read that exposes another tenant's data
requires an `X-API-Key` header, checked against RBAC roles (`admin`, `agent`,
`viewer`, `system`) defined in `backend/app/core/security.py`. Mint the first
key with `PHANTOM_BOOTSTRAP_ADMIN_KEY` set and `X-Bootstrap-Key` on the request
(`POST /api/v3/security/api-keys`); unset the env var afterwards.

**Tenant isolation on reads.** v3 (`/api/v3/events/chain/*`, `/api/v3/events/verify/*`)
is scoped to the caller's own `tenant_id` column; `admin`-role keys see across
tenants. v1/v2 (`/api/events`, `/api/state`, `/api/snapshots`, `/api/defi`) have
no `tenant_id` column of their own — rather than a schema migration, scoping
reuses the `EntityWorkspace` table (`backend/app/core/models_v2.py`), which
already mapped `entity_id -> workspace_id` but was previously only written by
`POST /api/workspaces/me/entities` and never read by anything. Every v1/v2
write path (`EventStore.append_event`, `DeFiEventManager.create_defi_event`)
now claims that link the first time an entity is written (first writer wins —
a tenant can never silently re-home an entity another tenant already claimed),
and every v1/v2 read filters through it: an entity with no link for the
caller's workspace 404s rather than returning data, including the "no snapshot
yet" fallback path that would otherwise replay another tenant's full v1 event
history. `Snapshot` and `DeFiEvent` already had their own `workspace_id`
column (same story — present, just never filtered on); creation now stamps it
from the caller's key rather than trusting a client-supplied value in the
request body.

## Plugin / strategy code execution

`POST /api/plugins/` and `POST /api/v3/strategies` accept a Python `code` string,
later run via `exec()` — treat `plugins:write`/`strategies:write` as equivalent to
granting code execution, not a data write. That code runs in an isolated
subprocess (`backend/app/core/sandbox.py`), never in the API process:
- **`SANDBOX_EXECUTOR=subprocess`** (default): a separate OS process, dropped to
  an unprivileged user (uid/gid 65534), with CPU/memory/file-size/process-count
  rlimits. This blocks the API process's own memory, env vars (no DB credentials
  reach the sandboxed code), and DB session from being reachable, and blocks
  fork/exec (tested: a classic restricted-`exec()` escape that reaches the `os`
  module can no longer spawn a shell once unprivileged + `RLIMIT_NPROC=0`). It
  does **not** block outbound network from sandboxed code.
- **`SANDBOX_EXECUTOR=docker`**: one throwaway `--network none --read-only
  --cap-drop ALL` container per call (same pattern as
  `agent-trust-layer/atl/executor.py` in this repo) — also closes the network
  gap. Needs direct Docker daemon access on the host running the backend.
  **Never** grant this by mounting `/var/run/docker.sock` into the backend's own
  container — that trades a sandbox escape for host-root access, which is worse.
  Only enable it when the backend runs outside a container, or has its own
  unshared daemon.
  **RAM-disk overlay** (`SANDBOX_RAMDISK=1`, default; `SANDBOX_RAMDISK_MB`,
  default 8): every writable path (`/tmp`, `/var/tmp`, `/run`, `/sandbox/work`)
  is a size-capped `noexec,nosuid,nodev` tmpfs, swap is disabled, container logs
  are off (`--log-driver none`), and the in-container entrypoint overwrites and
  unlinks all tmpfs files on exit/SIGTERM/SIGINT; timeouts force
  `docker rm -f -v`. Nothing reaches physical storage. Limits: SIGKILL/power loss
  rely on tmpfs volatility; host swap/hibernation/crash dumps are out of scope.

Restricting `__builtins__` inside the sandbox is defense in depth, not a
boundary by itself — it's a well-documented pattern to escape (no blocked
builtin is needed; `().__class__.__bases__[0].__subclasses__()` plus a bare
`except:` reaches arbitrary already-imported modules). The isolation above is
what actually bounds the damage once that escape is used.

### Frontend (.env)
```
VITE_BACKEND_URL=http://localhost:8001
```

## Database Schema

```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    entity_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_entity_created ON events(entity_id, created_at);
```

## Deployment

### Railway/Fly.io (Backend)
1. Deploy PostgreSQL database
2. Set `DATABASE_URL` environment variable
3. Deploy backend with Dockerfile

### Vercel (Frontend)
1. Set `VITE_BACKEND_URL` to your backend URL
2. Deploy from `/frontend` directory

## Cost Optimization

- No Redis required
- No vector database
- No LLM dependency
- Stateless compute (no memory overhead)
- Free-tier compatible (Supabase PostgreSQL, Railway, Vercel)

## Production Considerations

1. **Event Retention**: Implement archival for old events
2. **Indexes**: Ensure proper indexing on `entity_id` and `created_at`
3. **Caching**: Add Redis for frequently accessed state (optional)
4. **Rate Limiting**: Protect event ingestion endpoints
5. **Authentication**: Add auth middleware for production use

## License

MIT
