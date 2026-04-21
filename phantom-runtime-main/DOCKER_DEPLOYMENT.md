# Phantom Finance v3.0 - Docker Deployment Guide

## Quick Start

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+

### Local Development

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Access

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8001
- **API Docs**: http://localhost:8001/docs
- **PostgreSQL**: localhost:5432

### Environment Variables

Create a `.env` file in the root directory:

```env
POSTGRES_PASSWORD=your_secure_password
VITE_BACKEND_URL=http://localhost:8001
```

## Production Deployment

### Supabase PostgreSQL

1. Create a Supabase project
2. Get the connection string
3. Update `docker-compose.yml`:

```yaml
backend:
  environment:
    DATABASE_URL: your_supabase_connection_string
```

### Cloud Deployment (Railway/Fly.io)

#### Backend (Railway)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
cd backend
railway up
```

#### Frontend (Vercel)

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
cd frontend
vercel --prod
```

## Database Migration

### Initialize Database

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U postgres -d phantomos

# Verify tables
\dt

# Check event count
SELECT COUNT(*) FROM events_v3;
```

### Backup Database

```bash
# Export
docker-compose exec postgres pg_dump -U postgres phantomos > backup.sql

# Import
docker-compose exec -T postgres psql -U postgres phantomos < backup.sql
```

## Monitoring

### Health Checks

```bash
# Backend health
curl http://localhost:8001/api/health

# System info
curl http://localhost:8001/api/v3/system/info

# WebSocket test
wscat -c ws://localhost:8001/ws/events
```

### Performance Metrics

```bash
# Check database size
docker-compose exec postgres psql -U postgres -d phantomos -c "SELECT pg_size_pretty(pg_database_size('phantomos'));"

# Event statistics
docker-compose exec postgres psql -U postgres -d phantomos -c "SELECT event_type, COUNT(*) FROM events_v3 GROUP BY event_type;"
```

## Scaling

### Horizontal Scaling

```bash
# Scale backend
docker-compose up -d --scale backend=3

# Add load balancer (nginx)
docker-compose -f docker-compose.yml -f docker-compose.lb.yml up -d
```

### Database Optimization

```sql
-- Create indexes for performance
CREATE INDEX CONCURRENTLY idx_events_v3_tenant ON events_v3(tenant_id, created_at DESC);
CREATE INDEX CONCURRENTLY idx_events_v3_hash ON events_v3(event_hash);

-- Analyze tables
ANALYZE events_v3;
ANALYZE snapshots;
```

## Troubleshooting

### Backend not starting

```bash
# Check logs
docker-compose logs backend

# Verify database connection
docker-compose exec backend python -c "from app.core.database import engine; print(engine.connect())"
```

### Frontend build fails

```bash
# Rebuild without cache
docker-compose build --no-cache frontend

# Check Node version
docker-compose run frontend node --version
```

### WebSocket connection issues

- Ensure proxy/load balancer supports WebSocket
- Check CORS settings
- Verify firewall rules for port 8001

## Security Checklist

- [ ] Change default PostgreSQL password
- [ ] Enable SSL/TLS for production
- [ ] Set up firewall rules
- [ ] Use environment secrets (not .env in production)
- [ ] Enable API rate limiting
- [ ] Set up monitoring/alerting
- [ ] Regular database backups
- [ ] Implement log rotation

## License

MIT
