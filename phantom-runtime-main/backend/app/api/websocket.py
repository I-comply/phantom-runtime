from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from typing import List, Dict, Any
import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.event_buffer: List[Dict[str, Any]] = []
        self.max_buffer_size = 100
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
        
        # Send buffered events to new connection
        for event in self.event_buffer[-20:]:  # Last 20 events
            await websocket.send_json(event)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        # Add to buffer
        self.event_buffer.append(message)
        if len(self.event_buffer) > self.max_buffer_size:
            self.event_buffer.pop(0)
        
        # Broadcast to all connections
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for real-time event streaming"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and receive any client messages
            data = await websocket.receive_text()
            # Echo back as heartbeat
            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """WebSocket endpoint for real-time performance metrics"""
    await websocket.accept()
    try:
        while True:
            # Send metrics every second
            from app.core.database import SessionLocal
            from app.core.models_v3 import EventV3
            from app.core.models import Event
            
            db = SessionLocal()
            try:
                # Get metrics
                v3_count = db.query(EventV3).count()
                v1_count = db.query(Event).count()
                
                metrics = {
                    "type": "metrics_update",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "total_events_v3": v3_count,
                        "total_events_v1": v1_count,
                        "total_events": v3_count + v1_count,
                        "events_per_sec": 0,  # Calculate based on recent events
                        "active_connections": len(manager.active_connections)
                    }
                }
                
                await websocket.send_json(metrics)
            finally:
                db.close()
            
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

# Helper function to broadcast events (called from event creation)
async def broadcast_event(event_data: Dict[str, Any]):
    """Broadcast event to all WebSocket clients"""
    message = {
        "type": "new_event",
        "timestamp": datetime.utcnow().isoformat(),
        "data": event_data
    }
    await manager.broadcast(message)
