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
CORS_ORIGINS=*
```

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
