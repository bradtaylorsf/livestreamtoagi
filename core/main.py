import asyncio
import logging
import os
import time as _time
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from datetime import UTC
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from core.tts import TTSPipeline
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from core.admin import admin_router, auth_api, kill_switch_api
from core.bootstrap import Services, bootstrap_services, init_core_memories, shutdown_services
from core.event_bus import event_bus
from core.public_routes import router as public_router
from core.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT = 5.0  # seconds per check


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.idle_behavior import IdleBehaviorSystem
    from core.memory.reflection import ReflectionManager
    from core.tts import TTSPipeline
    from tools.journal_image_tool import JournalImageGenerator

    tts_pipeline = TTSPipeline()
    idle_behavior: IdleBehaviorSystem | None = None
    svc: Services | None = None

    svc = None
    try:
        svc = await bootstrap_services(auto_migrate=True)
        app.state.services = svc

        # Wire agent registry into TTS pipeline so voice IDs can be resolved.
        # TTSPipeline is created before bootstrap (to get its audio_dir for
        # the static mount), so the registry must be injected afterward.
        tts_pipeline._agent_registry = svc.agent_registry

        # Initialize core memory for all agents at startup
        if svc.core_memory:
            from core.constants import LIVE_SIMULATION_ID

            initialized = await init_core_memories(
                svc.agent_registry,
                svc.core_memory,
                simulation_id=LIVE_SIMULATION_ID,
            )
            if initialized:
                logger.info("Initialized core memory for: %s", ", ".join(initialized))

            # Health check: verify all agents have core memory
            for agent in svc.agent_registry.get_all_agents():
                mem = await svc.core_memory.get_core_memory(
                    agent.id, simulation_id=LIVE_SIMULATION_ID
                )
                if mem is None:
                    logger.warning("Agent %s still missing core memory after init", agent.id)

        await svc.config_loader.start_watching()

        journal_image_gen = JournalImageGenerator(cost_repo=svc.cost_repo)

        reflection_mgr = ReflectionManager(
            memory_repo=svc.memory_repo,
            llm_client=svc.llm_client,
            core_memory_mgr=svc.core_memory,
            token_counter=svc.token_counter,
            agent_registry=svc.agent_registry,
            goal_manager=svc.goal_manager,
            agent_state_manager=svc.agent_state_manager,
            dream_manager=svc.dream_manager,
            journal_image_generator=journal_image_gen,
            event_bus=svc.event_bus,
        )

        if svc.llm_client:
            start_scheduler(reflection_mgr, svc.agent_registry)

        idle_behavior = IdleBehaviorSystem(svc.agent_registry)
        idle_behavior.start()

        app.mount("/audio", StaticFiles(directory=str(tts_pipeline.audio_dir)), name="audio")
        app.state.tts_pipeline = tts_pipeline

        yield
    finally:
        if idle_behavior is not None:
            idle_behavior.stop()
        # Wait for background eval tasks to finish before closing services
        from core.admin import _background_tasks

        if _background_tasks:
            logger.info(
                "Waiting for %d background eval task(s) to finish...", len(_background_tasks)
            )
            await asyncio.gather(*_background_tasks, return_exceptions=True)

        await tts_pipeline.shutdown()
        if svc is not None:
            await svc.config_loader.stop_watching()
        stop_scheduler()
        await event_bus.shutdown()
        if svc is not None:
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
app.include_router(auth_api)
app.include_router(kill_switch_api)
app.include_router(public_router)


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


class EmitRequest(BaseModel):
    event_type: str
    data: dict[str, Any] = {}


class DevSimulateRequest(BaseModel):
    agents: list[str] | None = None
    topic: str | None = None
    turns: int = 5
    test_type: str = "freeform"  # "idle", "standup", "debate", "freeform"


_sim_tasks: set[asyncio.Task] = set()


async def _require_dev_mode() -> None:
    """Block dev endpoints in production.

    Dev endpoints are only available when ENV is 'development' (the default).
    Set ENV=production to disable them.
    """
    env = os.environ.get("ENV", "development")
    if env != "development":
        raise HTTPException(
            status_code=403,
            detail="Dev endpoints are disabled outside development mode",
        )


@app.post("/api/dev/simulate", dependencies=[Depends(_require_dev_mode)])
async def dev_simulate(req: DevSimulateRequest) -> dict[str, Any]:
    """Trigger a test conversation in-process so events reach WebSocket clients.

    Unlike the CLI simulation (which runs in a separate process with its own
    event_bus), this runs inside the FastAPI process so all emitted events are
    broadcast to connected browser clients immediately.

    Creates a real simulation record so the conversation is fully tracked and
    evaluatable via the /api/simulations endpoints.
    """
    import uuid as _uuid

    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.conversation_engine import ConversationEngine
    from core.models import SimulationCreate
    from core.redis_keys import ScopedRedis
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo

    svc: Services = app.state.services
    cfg = svc.config_loader.config

    # Create a tracked simulation record for this dev test
    sim_repo = SimulationRepo(svc.db)
    sim = await sim_repo.create(
        SimulationCreate(
            name=f"dev-test-{req.test_type}",
            description=f"Dev simulate: {req.test_type}, {req.turns} turns",
            config={"test_type": req.test_type, "topic": req.topic, "turns": req.turns},
        )
    )
    simulation_id = sim.id

    # Create a simulation-scoped Redis so all keys are isolated
    sim_redis = ScopedRedis(svc.redis, simulation_id)

    conversation_repo = ConversationRepo(svc.db)
    proximity = ProximityManager(sim_redis, cfg, event_bus)
    trigger_system = TriggerSystem(cfg.triggers, svc.recall_memory)
    selection_logger = SelectionLogger(conversation_repo, cfg.logging, simulation_id=simulation_id)

    trigger_map: dict[str, dict[str, Any]] = {
        "idle": {"type": "idle", "reason": "Free-form conversation", "location": "town_square"},
        "standup": {
            "type": "scheduled",
            "reason": "Daily standup",
            "starter_agent_id": "vera",
            "location": "town_square",
        },
        "debate": {
            "type": "environmental",
            "reason": "Debate topic",
            "topic": req.topic or "Should we rewrite everything in Rust?",
            "location": "workshop",
        },
        "freeform": {"type": "idle", "reason": "Free-form conversation", "location": "town_square"},
    }
    trigger = dict(trigger_map.get(req.test_type, trigger_map["freeform"]))
    if req.agents:
        trigger["starter_agent_id"] = req.agents[0]
    if req.topic:
        trigger["topic"] = req.topic

    agents = req.agents or [
        a.id for a in svc.agent_registry.get_all_agents() if a.id not in ("management", "alpha")
    ]
    task_id = str(_uuid.uuid4())
    max_turns = req.turns

    async def _run() -> None:
        tts_pipeline: TTSPipeline | None = getattr(app.state, "tts_pipeline", None)
        batch_ttl = max_turns * 15 + 300

        # ── Helpers ───────────────────────────────────────────────
        collected_turns: list[dict[str, Any]] = []
        tts_tasks: list[asyncio.Task[dict[str, Any] | None]] = []

        async def _gen_tts(data: dict[str, Any]) -> dict[str, Any] | None:
            if tts_pipeline is None:
                return None
            agent_id = data.get("agent_id", "")
            text = data.get("content") or data.get("dialogue") or data.get("text") or ""
            if not agent_id or not text:
                return None
            try:
                return await tts_pipeline.generate(agent_id, text, cleanup_ttl=batch_ttl)
            except (OSError, ValueError, RuntimeError):
                logger.exception("TTS pre-gen failed for %s", agent_id)
                return None

        async def _collect(evt: dict[str, Any]) -> None:
            if evt["event_type"] == "agent_speak":
                data = dict(evt["data"])
                collected_turns.append(data)
                # Kick off TTS immediately while LLM generates next turn
                tts_tasks.append(asyncio.create_task(_gen_tts(data)))

        # ── Phase 1: Run conversation silently, TTS overlaps ─────
        # Each turn's TTS starts generating as soon as the LLM produces it,
        # running in parallel with the LLM generating subsequent turns.
        class _SilentBus:
            def on(self, *_: object) -> None:
                pass

            def off(self, *_: object) -> None:
                pass

            async def emit(
                self, event_type: str, data: dict[str, Any] | None = None
            ) -> dict[str, Any]:
                evt = {
                    "event_type": event_type,
                    "event_id": str(_uuid_mod.uuid4()),
                    "timestamp": _time.time(),
                    "data": data or {},
                }
                await _collect(evt)
                return evt

        silent_bus = _SilentBus()

        from core.bootstrap import ConversationOptions, InfraServices, MemoryServices

        silent_engine = ConversationEngine(
            infra=InfraServices(
                config_loader=svc.config_loader,
                agent_registry=svc.agent_registry,
                event_bus=silent_bus,  # type: ignore[arg-type]
                llm_client=svc.llm_client,
                proximity=proximity,
                trigger_system=trigger_system,
                selection_logger=selection_logger,
            ),
            memory=MemoryServices(
                archival_memory=svc.archival_memory,
                compactor=svc.compactor,
                memory_repo=svc.memory_repo,
            ),
            options=ConversationOptions(
                speed_multiplier=1.0,
                management_enabled=True,
                simulation_id=simulation_id,
            ),
            management=svc.management,
            context_assembler=svc.context_assembler,
            conversation_repo=conversation_repo,
            services=svc,
        )

        try:
            print(f"[DEV-SIM] {task_id}: setting up proximity for {len(agents)} agents")
            for agent in svc.agent_registry.get_all_agents():
                await sim_redis.delete(f"agent:location:{agent.id}")
            location = str(trigger.get("location", "town_square"))
            for agent_id in agents:
                await proximity.update_location(agent_id, location)

            silent_engine._running = True
            print(f"[DEV-SIM] {task_id}: starting conversation (trigger={trigger.get('type')})")
            await silent_engine._start_conversation(trigger)

            if not silent_engine.active_conversation:
                print(
                    f"[DEV-SIM] {task_id}: WARNING - _start_conversation did not create an active conversation"
                )
                return

            turns_done = 0
            while (
                silent_engine.active_conversation
                and silent_engine.is_running
                and turns_done < max_turns
            ):
                print(f"[DEV-SIM] {task_id}: generating turn {turns_done + 1}/{max_turns}")
                should_continue = await silent_engine._continue_conversation()
                turns_done += 1
                print(
                    f"[DEV-SIM] {task_id}: turn {turns_done} done, collected {len(collected_turns)} speaks so far"
                )
                if not should_continue:
                    break
            if silent_engine.active_conversation:
                await silent_engine._end_conversation()
        except Exception:  # Broad catch: dev simulation must not crash the server
            logger.exception("Dev simulate task %s: conversation phase failed", task_id)
            return

        if not collected_turns:
            logger.warning("Dev simulate task %s: no turns collected", task_id)
            return

        print(
            f"[DEV-SIM] {task_id}: conversation done, {len(collected_turns)} turns collected, {len(tts_tasks)} TTS tasks pending"
        )

        # ── Phase 2: Replay immediately ──────────────────────────
        # TTS was kicked off during Phase 1 in parallel with LLM generation,
        # so most/all audio is already ready.  Await each in order and play
        # back-to-back with no dead time between speakers.
        for i, (turn_data, tts_task) in enumerate(
            zip(collected_turns, tts_tasks, strict=False),
        ):
            tts = await tts_task
            emit_data = dict(turn_data)
            duration = 3.0

            if tts:
                duration = float(tts["duration"])
                emit_data["segments"] = [
                    {
                        "text": tts["text"],
                        "audio_url": tts["audio_url"],
                        "duration": duration,
                        "action": None,
                    }
                ]
                print(
                    f"[DEV-SIM] {task_id}: playing turn {i + 1}/{len(collected_turns)} ({turn_data.get('agent_id')}, {duration:.1f}s)"
                )
            else:
                print(
                    f"[DEV-SIM] {task_id}: WARNING - turn {i + 1}/{len(collected_turns)} has no TTS"
                )

            await event_bus.emit("agent_speak", emit_data)
            await asyncio.sleep(duration + 0.5)

        print(f"[DEV-SIM] {task_id}: playback complete")

        # Finalize simulation as completed
        from datetime import datetime

        await sim_repo.update_status(simulation_id, "completed", completed_at=datetime.now(UTC))
        await sim_repo.update_agents_participated(simulation_id, agents)

    async def _run_with_finalize() -> None:
        try:
            await _run()
        except Exception:  # Broad catch: must finalize simulation status on any failure
            from datetime import datetime

            logger.exception("Dev simulate task %s failed", task_id)
            await sim_repo.update_status(
                simulation_id,
                "failed",
                completed_at=datetime.now(UTC),
                error_log={"task_id": task_id, "error": "unhandled exception"},
            )

    def _on_done(t: asyncio.Task) -> None:
        _sim_tasks.discard(t)
        if t.cancelled():
            print(f"[DEV-SIM] {task_id}: task was cancelled")
        elif t.exception():
            print(f"[DEV-SIM] {task_id}: UNHANDLED EXCEPTION: {t.exception()!r}")
            import traceback

            traceback.print_exception(
                type(t.exception()), t.exception(), t.exception().__traceback__
            )

    task = asyncio.create_task(_run_with_finalize())
    _sim_tasks.add(task)
    task.add_done_callback(_on_done)
    return {
        "ok": True,
        "task_id": task_id,
        "simulation_id": str(simulation_id),
        "agents": agents,
        "turns": max_turns,
    }


@app.post("/api/dev/emit", dependencies=[Depends(_require_dev_mode)])
async def dev_emit(req: EmitRequest) -> dict[str, Any]:
    """Inject an event into the event bus (dev/CLI use only).

    Called by scripts like pnpm chat so that agent responses are broadcast
    to connected Phaser frontend clients without needing to be in-process.

    When event_type is "agent_speak" and the data includes "text" + "agent_id",
    TTS is generated automatically and a "tts_play" event is also emitted so the
    frontend AudioManager plays the voice.
    """
    data = dict(req.data)

    # Generate TTS server-side only when the caller hasn't already done it.
    # If "duration" is present, the CLI already generated audio and timed the
    # bubble — skip server-side TTS to avoid double generation and stale timing.
    if (
        req.event_type == "agent_speak"
        and "text" in data
        and "agent_id" in data
        and "duration" not in data
    ):
        tts: TTSPipeline | None = getattr(app.state, "tts_pipeline", None)
        if tts is not None:
            try:
                segments = await tts.speak_segmented(data["agent_id"], data["text"])
                if segments:
                    data["segments"] = segments
                    # Backward-compat: set audio_url/duration from the first segment so
                    # older clients that don't understand segments still get some audio.
                    first = segments[0]
                    data["audio_url"] = first["audio_url"]
                    data["duration"] = int(first["duration"] * 1000)
            except (OSError, ValueError, RuntimeError):
                logger.exception("TTS generation failed in dev_emit")

    event = await event_bus.emit(req.event_type, data)
    return {"ok": True, "event_id": event["event_id"]}


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
