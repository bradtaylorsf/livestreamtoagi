#!/usr/bin/env python3
"""Run a scenario in **headless** mode.

A headless run executes the same conversation engine, dreams, relationships,
alliances, and shared blackboard as an embodied run, but does **not** import
or initialize Director V2, Mindcraft, the TTS pipeline, or the audio FIFO.
Tool intents are recorded and simulated deterministically.

Output is written to a self-contained sim folder under ``--output-dir`` so the
artifacts can be replayed and evaluated downstream (see
``scripts/replay_in_minecraft.py``).

Example:

    python scripts/run_headless_sim.py \\
        --scenario scenarios/dream_smoke_test.yaml \\
        --max-cost 0.01 \\
        --seed 42
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _default_agents() -> list[str]:
    """Build the default agent roster (excludes 'management')."""
    from core.agent_registry import AgentRegistry

    registry = AgentRegistry(redis_client=None)
    agents = registry._load_all_from_yaml()
    return [a for a in agents if a != "management"]


def _agents_from_scenario(path: Path) -> list[str]:
    import yaml

    if not path.is_file():
        return []
    parsed = yaml.safe_load(path.read_text()) or {}
    if not isinstance(parsed, dict):
        return []
    raw_agents = parsed.get("agents")
    if raw_agents is None and isinstance(parsed.get("meta"), dict):
        raw_agents = parsed["meta"].get("agents")
    if isinstance(raw_agents, str):
        raw_agents = raw_agents.split(",")
    if not isinstance(raw_agents, list):
        return []
    return [a.strip() for a in raw_agents if isinstance(a, str) and a.strip()]


def _resolve_scenario(scenario_arg: str) -> Path:
    """Resolve a scenario arg to an absolute path under ``scenarios/``."""
    candidate = Path(scenario_arg)
    if candidate.is_file():
        return candidate.resolve()
    if not candidate.is_absolute():
        rel = (PROJECT_ROOT / candidate).resolve()
        if rel.is_file():
            return rel
        # Allow bare scenario names like "dream_smoke_test".
        bare = (PROJECT_ROOT / "scenarios" / candidate.name).with_suffix(".yaml").resolve()
        if bare.is_file():
            return bare
    raise FileNotFoundError(f"scenario not found: {scenario_arg}")


def _build_output_folder(output_dir: Path, name: str) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    folder = output_dir / f"{timestamp}_{name}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_metadata(sim_folder: Path, payload: dict) -> None:
    (sim_folder / "metadata.json").write_text(json.dumps(payload, indent=2, default=str))


async def run_headless(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpcore", "httpx", "asyncpg", "urllib3", "hpack", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.seed is not None:
        random.seed(args.seed)

    scenario_path = _resolve_scenario(args.scenario)
    name = args.name or f"headless-{scenario_path.stem}-{uuid.uuid4().hex[:6]}"

    output_dir = Path(args.output_dir).expanduser().resolve()
    sim_folder = _build_output_folder(output_dir, name)

    # Set log destination via env so downstream pieces (decision logger) can
    # discover it without threading the path through every constructor.
    os.environ.setdefault("HEADLESS_SIM_FOLDER", str(sim_folder))

    # Local imports keep top-level startup cheap and ensure the headless path
    # never pulls Director V2 / Mindcraft / TTS at import time.
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import event_bus
    from core.memory.reflection import ReflectionManager
    from core.minecraft.build_plan_catalog import build_plan_catalog_resolver
    from core.minecraft.build_plan_compiler import BuildPlanCompiler
    from core.models import RunMode
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.clock import SimulationClock
    from core.simulation.decision_logger import DecisionLogger
    from core.simulation.display import SimulationDisplay
    from core.simulation.orchestrator import (
        SimulationConfig,
        SimulationOrchestrator,
        parse_duration,
    )
    from tools.journal_image_tool import JournalImageGenerator

    duration = parse_duration(args.duration) if args.duration else None
    scenario_agents = _agents_from_scenario(scenario_path) or _default_agents()

    sim_config = SimulationConfig(
        name=name,
        description=args.description,
        seed_file=str(scenario_path),
        agents=scenario_agents,
        max_cost=args.max_cost,
        speed_multiplier=args.speed_multiplier,
        duration=duration,
        run_mode=RunMode.headless,
        scenario_id=scenario_path.stem,
        existing_sim_id=args.sim_id,
    )
    sim_config.load_seed_file(valid_agent_ids=set(scenario_agents))

    metadata = {
        "name": name,
        "scenario": str(scenario_path),
        "scenario_id": scenario_path.stem,
        "run_mode": "headless",
        "seed": args.seed,
        "max_cost": args.max_cost,
        "speed_multiplier": args.speed_multiplier,
        "duration_seconds": duration.total_seconds() if duration else None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "agents": scenario_agents,
    }
    _write_metadata(sim_folder, metadata)

    svc = await bootstrap_services(auto_migrate=True)
    cfg = svc.config_loader.config

    conversation_repo = ConversationRepo(svc.db)
    simulation_repo = SimulationRepo(svc.db)

    proximity = ProximityManager(
        svc.redis,
        cfg,
        event_bus,
        role_bonuses=svc.agent_registry.get_role_bonuses(),
    )
    sim_clock = SimulationClock(speed_multiplier=sim_config.speed_multiplier)
    trigger_system = TriggerSystem(
        cfg.triggers,
        svc.recall_memory,
        goal_manager=svc.goal_manager,
        agent_state_manager=svc.agent_state_manager,
        clock=sim_clock,
        now_fn=sim_clock.now,
    )
    selection_logger = SelectionLogger(conversation_repo, cfg.logging)

    if svc.event_generator is not None:
        svc.event_generator._triggers = trigger_system

    journal_image_gen = JournalImageGenerator(cost_repo=svc.cost_repo)
    reflection_manager = ReflectionManager(
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

    display = SimulationDisplay(verbose=args.verbose, agent_registry=svc.agent_registry)

    # Wire the BuildPlanCompiler + static catalog resolver so `propose_build`
    # writes a compiled BuildScript per intent (issue #888). Without this
    # the executor's _maybe_write_build_script early-returns and the
    # live-RCON hook stays dormant in headless mode.
    build_plan_compiler = BuildPlanCompiler()
    build_plan_resolver = build_plan_catalog_resolver()

    orchestrator = SimulationOrchestrator(
        config=sim_config,
        db=svc.db,
        redis_client=svc.redis,
        simulation_repo=simulation_repo,
        config_loader=svc.config_loader,
        agent_registry=svc.agent_registry,
        event_bus=event_bus,
        llm_client=svc.llm_client,
        management=svc.management,
        context_assembler=svc.context_assembler,
        conversation_repo=conversation_repo,
        archival_memory=svc.archival_memory,
        proximity=proximity,
        trigger_system=trigger_system,
        selection_logger=selection_logger,
        reflection_manager=reflection_manager,
        compactor=svc.compactor,
        memory_repo=svc.memory_repo,
        display=display,
        services=svc,
        clock=sim_clock,
        relationship_repo=svc.relationship_repo,
        build_plan_compiler=build_plan_compiler,
        build_plan_resolver=build_plan_resolver,
    )

    orchestrator._sim_folder = sim_folder
    orchestrator._decision_logger = DecisionLogger(sim_folder)
    # Per-sim ownership ledger (#891) — replays existing
    # <sim>/ownership_log.jsonl so resumed runs inherit prior claims.
    from core.civilization.ownership import OwnershipLedger
    from core.civilization.trade import TradeLedger

    orchestrator._ownership_ledger = OwnershipLedger(sim_folder)
    # Per-sim trade ledger (#892) — replays <sim>/trade_log.jsonl.
    orchestrator._trade_ledger = TradeLedger(sim_folder)
    # Per-sim theft ledger (#893) — shares the trade inventory model and
    # replays <sim>/theft_log.jsonl.
    from core.civilization.theft import TheftLedger

    orchestrator._theft_ledger = TheftLedger(
        sim_folder,
        trade_ledger=orchestrator._trade_ledger,
        ownership_ledger=orchestrator._ownership_ledger,
        simulation_id=args.sim_id or name,
    )

    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        from core.simulation.display import console

        console.print("\n[dim]Cancelling headless simulation...[/dim]")
        orchestrator.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        if sim_config.mode == "autonomous":
            await orchestrator.run_autonomous()
        else:
            await orchestrator.run()
    finally:
        try:
            orchestrator._decision_logger.close()
        except Exception:  # pragma: no cover
            pass
        metadata["completed_at"] = datetime.utcnow().isoformat() + "Z"
        metadata["simulation_id"] = (
            str(orchestrator.simulation_id) if orchestrator.simulation_id else None
        )
        _write_metadata(sim_folder, metadata)

        if not args.skip_eval:
            try:
                from core.eval.headless_scorer import HeadlessScorer

                scorer = HeadlessScorer(sim_folder, llm_client=svc.llm_client)
                await scorer.score()
            except FileNotFoundError:
                # decision_log.jsonl never written — nothing to score.
                logging.getLogger(__name__).warning(
                    "headless eval scoring skipped: decision log missing"
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "headless eval scoring failed (sim artifacts intact)"
                )

        await shutdown_services(svc)

    print(f"Headless simulation complete. Artifacts: {sim_folder}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a scenario in headless mode (no Minecraft/Mindcraft/TTS)."
    )
    parser.add_argument("--scenario", type=str, required=True, help="Scenario YAML path or name")
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        help="Optional simulated duration (e.g. '12h', '7d', '90m').",
    )
    parser.add_argument(
        "--speed-multiplier",
        type=float,
        default=0,
        help="Simulated clock speed (0=instant, 42=42x).",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=1.0,
        help="Max LLM spend in USD before the run stops.",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "snapshots" / "headless"),
        help="Folder under which sim artifacts are written.",
    )
    parser.add_argument("--name", type=str, default=None, help="Override the generated sim name.")
    parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Free-form description stored on the simulation row.",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip post-run headless eval scoring (decision log still written).",
    )
    parser.add_argument(
        "--sim-id",
        type=str,
        default=None,
        help="Use a pre-created simulations row UUID instead of creating one.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    parser = _build_parser()
    args = parser.parse_args(argv)
    asyncio.run(run_headless(args))


if __name__ == "__main__":
    main()
