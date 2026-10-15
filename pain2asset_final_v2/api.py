import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from models import AssetPackageRequest, AssetPackageResponse
from db import DatabaseManager
from rss_scraper import FullyHardenedScraper
from packager import AssetPackagerEngine
from ws_engine import RealTimeLLMRouter

logger = logging.getLogger("api")

db = DatabaseManager(os.getenv("DATABASE_PATH", "data/pain2asset.db"))
scraper = FullyHardenedScraper(db, interval_seconds=int(os.getenv("SCRAPE_INTERVAL_SECONDS", "300")))
packager = AssetPackagerEngine()
llm_router = RealTimeLLMRouter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await scraper.start()
    yield
    await scraper.stop()

app = FastAPI(title="Pain2Asset Forge", version="7.0.0", lifespan=lifespan)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def index():
    return FileResponse("static/index.html")

@app.post("/v1/assets/package", response_model=AssetPackageResponse, status_code=status.HTTP_201_CREATED)
def package_asset(request: AssetPackageRequest):
    try:
        packaged = packager.package_asset(request)
        db.save_package({**packaged.model_dump(), "description": request.description})
        return packaged
    except Exception:
        logger.exception("Asset packaging failed")
        raise HTTPException(status_code=500, detail="Asset packaging failed")

@app.get("/v1/painpoints", status_code=status.HTTP_200_OK)
def get_pain_points():
    return {"pain_points": db.get_recent_pain_points(30)}

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    try:
        db.get_recent_pain_points(1)
        db_state = "connected"
    except Exception:
        db_state = "error"
    return {
        "status": "healthy" if db_state == "connected" else "degraded",
        "database": db_state,
        "rss_scraper": "running" if scraper._running else "stopped",
    }

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        await websocket.send_json({"sender": "System", "message": "Connected to Pain2Asset Forge Real-Time LLM Gateway."})
        while True:
            data = await websocket.receive_text()
            response_text = await llm_router.generate_response(data[:8000])
            await websocket.send_json({"sender": "Pain2Asset AI", "message": response_text})
    except WebSocketDisconnect:
        pass
