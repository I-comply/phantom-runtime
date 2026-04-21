from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, SessionLocal
from app.api import routes_events, routes_state
from app.api import routes_workspaces, routes_snapshots, routes_plugins, routes_defi
from app.api import routes_v3
from app.api import websocket
from app.core.security import SecurityManager
import logging

# Initialize database (creates all tables including v3)
init_db()

# Initialize RBAC roles
db = SessionLocal()
try:
    SecurityManager.initialize_roles(db)
finally:
    db.close()

app = FastAPI(
    title="Phantom Finance - Next-Gen Event Runtime",
    version="3.0.0",
    description="Premium event-sourcing platform with hash-chained events, async pipeline, and strategy execution"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include v1/v2 routers (backward compatible)
app.include_router(routes_events.router)
app.include_router(routes_state.router)
app.include_router(routes_workspaces.router)
app.include_router(routes_snapshots.router)
app.include_router(routes_plugins.router)
app.include_router(routes_defi.router)

# Include v3 router (next-gen features)
app.include_router(routes_v3.router)

# Include WebSocket routes
app.include_router(websocket.router)

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Phantom Finance",
        "version": "3.0.0",
        "codename": "DARK_OPERATOR",
        "websocket": "enabled"
    }

@app.get("/")
async def root():
    return {
        "platform": "Phantom Finance v3.0",
        "tagline": "Next-Gen Event Runtime + Strategy Execution Platform",
        "api_docs": "/docs",
        "websocket": {
            "events": "/ws/events",
            "metrics": "/ws/metrics"
        },
        "versions": {
            "v1": "/api/events, /api/state (backward compatible)",
            "v2": "/api/workspaces, /api/snapshots, /api/plugins, /api/defi",
            "v3": "/api/v3/* (hash-chained events, async pipeline, strategies)"
        }
    }

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
