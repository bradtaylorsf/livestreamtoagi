import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.agent_registry import AgentRegistry
from core.database import Database
from core.event_bus import event_bus
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT = 5.0  # seconds per check

db = Database()
redis_client = RedisClient()
agent_registry = AgentRegistry(redis_client=redis_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db.connect()
        await redis_client.connect()
        await agent_registry.load_all()
        yield
    finally:
        await event_bus.shutdown()
        await redis_client.disconnect()
        await db.disconnect()


app = FastAPI(title="Livestream AGI", version="0.1.0", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    client_id = await event_bus.connect(ws)
    try:
        while True:
            # Keep connection alive; ignore client messages for now
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await event_bus.disconnect(client_id)


@app.get("/api/health")
async def health() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(db.fetchval("SELECT 1"), timeout=HEALTH_CHECK_TIMEOUT)
        checks["database"] = "ok"
    except TimeoutError:
        checks["database"] = "timeout"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=HEALTH_CHECK_TIMEOUT)
        checks["redis"] = "ok"
    except TimeoutError:
        checks["redis"] = "timeout"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}
