import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from core.admin_routes import router as admin_router
from core.bootstrap import Services, bootstrap_services, shutdown_services
from core.event_bus import event_bus
from core.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT = 5.0  # seconds per check


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.memory.reflection import ReflectionManager
    from core.tts import TTSPipeline

    tts_pipeline = TTSPipeline()

    try:
        svc = await bootstrap_services()
        app.state.services = svc

        await svc.config_loader.start_watching()

        api_key = os.environ.get("OPENROUTER_API_KEY", "")

        reflection_mgr = ReflectionManager(
            memory_repo=svc.memory_repo,
            llm_client=svc.llm_client,
            core_memory_mgr=svc.core_memory,
            token_counter=svc.token_counter,
            agent_registry=svc.agent_registry,
        )

        if api_key:
            start_scheduler(reflection_mgr, svc.agent_registry)

        app.mount("/audio", StaticFiles(directory=str(tts_pipeline.audio_dir)), name="audio")
        app.state.tts_pipeline = tts_pipeline

        yield
    finally:
        await tts_pipeline.shutdown()
        await svc.config_loader.stop_watching()
        stop_scheduler()
        await event_bus.shutdown()
        await shutdown_services(svc)


app = FastAPI(title="Livestream AGI", version="0.1.0", lifespan=lifespan)

_default_origins = ["http://localhost:3000", "http://localhost:4000", "http://localhost:5173"]
_extra = os.environ.get("CORS_ORIGINS", "")
_cors_origins = _default_origins + [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
    svc: Services = app.state.services
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(svc.db.fetchval("SELECT 1"), timeout=HEALTH_CHECK_TIMEOUT)
        checks["database"] = "ok"
    except TimeoutError:
        checks["database"] = "timeout"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        await asyncio.wait_for(svc.redis.ping(), timeout=HEALTH_CHECK_TIMEOUT)
        checks["redis"] = "ok"
    except TimeoutError:
        checks["redis"] = "timeout"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}
