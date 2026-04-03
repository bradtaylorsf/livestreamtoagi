import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from core.admin_routes import router as admin_router
from core.agent_registry import AgentRegistry
from core.config_loader import ConfigLoader
from core.database import Database
from core.event_bus import event_bus
from core.redis_client import RedisClient
from core.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT = 5.0  # seconds per check

db = Database()
redis_client = RedisClient()
agent_registry = AgentRegistry(redis_client=redis_client)
config_loader = ConfigLoader()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start reflection scheduler (lazy imports to avoid circular deps)
    import os

    from core.llm_client import OpenRouterClient
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.reflection import ReflectionManager
    from core.memory.token_counter import TokenCounter
    from core.repos.cost_repo import CostRepo
    from core.repos.memory_repo import MemoryRepo
    from core.tts import TTSPipeline

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    llm_client = None
    tts_pipeline = TTSPipeline()

    try:
        await db.connect()
        await redis_client.connect()
        await agent_registry.load_all()
        config_loader.load()
        await config_loader.start_watching()

        cost_repo = CostRepo(db)
        memory_repo = MemoryRepo(db)
        token_counter = TokenCounter()
        llm_client = OpenRouterClient(api_key=api_key, cost_repo=cost_repo)
        core_memory_mgr = CoreMemoryManager(memory_repo=memory_repo, token_counter=token_counter)

        reflection_mgr = ReflectionManager(
            memory_repo=memory_repo,
            llm_client=llm_client,
            core_memory_mgr=core_memory_mgr,
            token_counter=token_counter,
            agent_registry=agent_registry,
        )

        if api_key:
            start_scheduler(reflection_mgr, agent_registry)

        app.mount("/audio", StaticFiles(directory=str(tts_pipeline.audio_dir)), name="audio")
        app.state.tts_pipeline = tts_pipeline

        yield
    finally:
        await tts_pipeline.shutdown()
        await config_loader.stop_watching()
        stop_scheduler()
        if api_key and llm_client:
            await llm_client.close()
        await event_bus.shutdown()
        await redis_client.disconnect()
        await db.disconnect()


app = FastAPI(title="Livestream AGI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:4000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)


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
