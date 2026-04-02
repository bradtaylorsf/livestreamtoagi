import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.agent_registry import AgentRegistry
from core.database import Database
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

db = Database()
redis_client = RedisClient()
agent_registry = AgentRegistry(redis_client=redis_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await redis_client.connect()
    await agent_registry.load_all()
    yield
    await redis_client.disconnect()
    await db.disconnect()


app = FastAPI(title="Livestream AGI", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, str]:
    checks = {}
    try:
        await db.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    try:
        await redis_client.client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}
