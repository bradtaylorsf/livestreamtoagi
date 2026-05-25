#!/usr/bin/env python3
"""CLI entry point for the simulation orchestrator.

Seeded mode (phase-based):
    python scripts/run_simulation.py \\
      --name "test-run-001" \\
      --seed-file scenarios/full_day.yaml \\
      --max-cost 10.00 --verbose

Autonomous mode (trigger-driven):
    python scripts/run_simulation.py \\
      --name "week-test" \\
      --duration 7d --speed-multiplier 42 --max-cost 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import timedelta
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from core.models import ManagementPolicy  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_AGENT_ORDER = ("alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")
DEFAULT_AGENT_EXCLUDE = frozenset({"management"})


def _default_agents() -> str:
    """Build default simulation roster from real agent configs."""
    from core.agent_registry import AgentRegistry

    registry = AgentRegistry(redis_client=None)
    agents = registry._load_all_from_yaml()
    available = {agent_id for agent_id in agents if agent_id not in DEFAULT_AGENT_EXCLUDE}
    ordered = [agent_id for agent_id in DEFAULT_AGENT_ORDER if agent_id in available]
    ordered.extend(sorted(available.difference(ordered)))
    return ",".join(ordered)


DEFAULT_AGENTS = _default_agents()


def _load_run_config_file(path: str | None) -> dict:
    """Load a JSON run config produced by public simulation submission."""
    if not path:
        return {}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("--run-config-file must contain a JSON object")
    return data


def _agents_from_seed_file(path: str | None) -> list[str]:
    if not path:
        return []
    import yaml

    seed_path = Path(path)
    if not seed_path.is_absolute():
        seed_path = PROJECT_ROOT / seed_path
    if not seed_path.is_file():
        return []
    parsed = yaml.safe_load(seed_path.read_text()) or {}
    if not isinstance(parsed, dict):
        return []
    raw_agents = parsed.get("agents")
    if raw_agents is None and isinstance(parsed.get("meta"), dict):
        raw_agents = parsed["meta"].get("agents")
    if isinstance(raw_agents, str):
        raw_agents = raw_agents.split(",")
    if not isinstance(raw_agents, list):
        return []
    return [agent.strip() for agent in raw_agents if isinstance(agent, str) and agent.strip()]


def _agents_from_run_config(args: argparse.Namespace, run_config: dict) -> list[str]:
    raw_agents = run_config.get("agents")
    if raw_agents is None:
        raw_agents = getattr(args, "agents", None)
    if raw_agents is None:
        raw_agents = _agents_from_seed_file(getattr(args, "seed_file", None)) or DEFAULT_AGENTS
    if isinstance(raw_agents, str):
        raw_agents = raw_agents.split(",")
    if not isinstance(raw_agents, list):
        raise ValueError("run config agents must be a list or comma-separated string")
    return [a.strip() for a in raw_agents if isinstance(a, str) and a.strip()]


def _memory_seed_from_run_config(args: argparse.Namespace, run_config: dict):
    """Build MemorySeedConfig from CLI flags first, then run config."""
    from core.models import MemorySeedConfig

    if args.memory_seed_mode:
        return MemorySeedConfig(
            mode=args.memory_seed_mode,
            inherit_from=args.memory_seed_inherit_from,
            custom_file=args.memory_seed_file,
        )

    raw = run_config.get("memory_seed")
    if not isinstance(raw, dict) or not raw.get("mode"):
        return None

    if raw.get("mode") == "inherit" and not raw.get("inherit_from"):
        raw = {**raw, "inherit_from": raw.get("simulation_id")}
    if raw.get("mode") == "custom" and not raw.get("custom_file"):
        raise ValueError("run config memory_seed mode='custom' requires custom_file")

    return MemorySeedConfig(
        mode=raw.get("mode"),
        inherit_from=raw.get("inherit_from"),
        custom_file=raw.get("custom_file"),
    )


def _world_from_run_config(args: argparse.Namespace, run_config: dict) -> dict | None:
    """Build world config from CLI flags first, then run config."""
    if args.world_config_file:
        return {
            "world_type": "custom",
            "world_config_path": args.world_config_file,
        }
    raw = run_config.get("world")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("run config world must be an object")
    return raw


def _duration_from_hours(value: float | None) -> timedelta | None:
    if value is None:
        return None
    if value <= 0:
        raise ValueError("--duration-hours must be greater than zero")
    return timedelta(seconds=value * 3600)


async def run_simulation(args: argparse.Namespace) -> None:
    """Main async entry point."""
    verbose = getattr(args, "verbose", False)
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Only enable DEBUG on our modules — silence noisy HTTP libraries
    if verbose:
        for module in ("core", "tools", "scripts"):
            logging.getLogger(module).setLevel(logging.DEBUG)
    # Always silence HTTP-level noise (httpcore, httpx, asyncpg, urllib3)
    for noisy in ("httpcore", "httpx", "asyncpg", "urllib3", "hpack", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from core.bootstrap import bootstrap_services, shutdown_services
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.conversation_mode import get_conversation_mode
    from core.event_bus import event_bus
    from core.memory.reflection import ReflectionManager
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.clock import SimulationClock
    from core.simulation.display import SimulationDisplay
    from core.simulation.orchestrator import (
        SimulationConfig,
        SimulationOrchestrator,
        parse_duration,
        parse_experimental_goal,
    )
    from tools.journal_image_tool import JournalImageGenerator

    # ── Parse simulation config ───────────────────────────
    run_config = _load_run_config_file(getattr(args, "run_config_file", None))
    agents = _agents_from_run_config(args, run_config)

    duration = None
    if getattr(args, "duration_hours", None) is not None:
        duration = _duration_from_hours(args.duration_hours)
    elif args.duration:
        duration = parse_duration(args.duration)

    experimental_goal = None
    if getattr(args, "experimental_goal", None):
        experimental_goal = parse_experimental_goal(args.experimental_goal)

    rolling_window = None
    if args.rolling_window:
        rolling_window = parse_duration(args.rolling_window)
        if rolling_window.total_seconds() <= 0:
            raise ValueError("--rolling-window must be greater than zero")

    # Build memory_seed config from CLI flags or public run config.
    memory_seed_cfg = _memory_seed_from_run_config(args, run_config)
    world_cfg = _world_from_run_config(args, run_config)

    sim_config = SimulationConfig(
        name=args.name,
        description=args.description,
        seed_file=args.seed_file,
        agents=agents,
        max_cost=args.max_cost,
        max_cost_rolling=args.max_cost_rolling,
        rolling_window=rolling_window,
        speed=args.speed,
        speed_multiplier=args.speed_multiplier,
        duration=duration,
        dry_run=args.dry_run,
        verbose=verbose,
        management_shadow=args.management_shadow,
        management_policy=args.management_policy or run_config.get("management_policy"),
        existing_sim_id=getattr(args, "resume_sim_id", None) or getattr(args, "sim_id", None),
        hypothesis=getattr(args, "hypothesis", None),
        auto_draft_learnings=getattr(args, "auto_draft_learnings", False),
        memory_seed=memory_seed_cfg,
        persona_overrides=run_config.get("persona_overrides"),
        agent_goals=run_config.get("agent_goals"),
        world_config=world_cfg,
        run_mode=args.run_mode or run_config.get("run_mode"),
        experimental_goal=experimental_goal or run_config.get("experimental_goal"),
        scenario_id=run_config.get("scenario_id"),
        scenario_meta=run_config.get("scenario_meta"),
        scenario_agents=run_config.get("scenario_agents"),
        excluded_agents=run_config.get("excluded_agents"),
        factions=run_config.get("factions"),
        initial_agent_energy=run_config.get("energy"),
        conversation_cadence=run_config.get("conversation_cadence", 1.0),
        conversation_mode=args.conversation_mode or get_conversation_mode(),
        submitted_params=run_config.get("params"),
        source=run_config.get("source"),
    )
    sim_config.world_sim = args.world_sim
    # Validate faction membership against the participating-agents set so
    # misconfigured scenarios fail loudly at load time.
    sim_config.load_seed_file(valid_agent_ids=set(agents))
    if sim_config.world_config is not None:
        world_path = sim_config.world_config.world_config_path or "(derived from run spec)"
        logging.getLogger(__name__).info(
            "Run world: path=%s run_mode=%s persistent=%s",
            world_path,
            sim_config.run_mode.value if sim_config.run_mode is not None else "unspecified",
            sim_config.world_config.persistent,
        )

    # ── Connect services ──────────────────────────────────
    svc = await bootstrap_services(auto_migrate=True)
    cfg = svc.config_loader.config

    conversation_repo = ConversationRepo(svc.db)
    simulation_repo = SimulationRepo(svc.db)

    if sim_config.conversation_mode in {"embodied", "director_v2"} and not getattr(
        args, "no_embodied_supervisor", False
    ):
        from core.simulation.embodied_supervisor import EmbodiedSimulationSupervisor

        supervisor = EmbodiedSimulationSupervisor(
            config=sim_config,
            simulation_repo=simulation_repo,
            redis_client=svc.redis,
            project_root=PROJECT_ROOT,
            run_dir=Path(args.minecraft_log_dir) if args.minecraft_log_dir else None,
            run_eval=not args.no_embodied_eval,
            run_report=not args.no_embodied_report,
        )
        try:
            result = await supervisor.run()
            print(
                "Embodied supervisor completed "
                f"simulation_id={result.simulation_id} "
                f"run_id={result.run_id} "
                f"status={result.status.value} "
                f"stop_reason={result.stop_reason}"
            )
            return
        finally:
            await shutdown_services(svc)

    if sim_config.management_policy is not None:
        from core.management import Management

        management = Management(
            redis_client=svc.redis,
            llm_client=svc.llm_client,
            event_bus=event_bus,
            policy=sim_config.management_policy,
            db=svc.db,
        )
    else:
        management = svc.management

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

    # Wire trigger system into event generator (#273)
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

    display = SimulationDisplay(verbose=verbose, agent_registry=svc.agent_registry)

    # ── Build orchestrator ────────────────────────────────
    orchestrator = SimulationOrchestrator(
        config=sim_config,
        db=svc.db,
        redis_client=svc.redis,
        simulation_repo=simulation_repo,
        config_loader=svc.config_loader,
        agent_registry=svc.agent_registry,
        event_bus=event_bus,
        llm_client=svc.llm_client,
        management=management,
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
    )

    # ── Signal handling ───────────────────────────────────
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        from core.simulation.display import console

        console.print("\n[dim]Cancelling simulation...[/dim]")
        orchestrator.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # ── Restore snapshot if provided ──────────────────────
    if args.restore_snapshot:
        import json as _json

        from core.memory.snapshot import MemorySnapshotImporter

        snapshot_data = _json.loads(Path(args.restore_snapshot).read_text())
        importer = MemorySnapshotImporter(
            db=svc.db,
            memory_repo=svc.memory_repo,
            core_memory_mgr=svc.core_memory,
            recall_memory_mgr=svc.recall_memory,
            relationship_repo=svc.relationship_repo,
            embedding_fn=None,  # Use embedded vectors from snapshot
            token_counter=svc.token_counter,
        )
        restore_result = await importer.restore(snapshot_data)
        logger = logging.getLogger(__name__)
        logger.info(
            "Restored snapshot: %d agents, %d core, %d recall, %d journal, %d relationships",
            len(restore_result.agents_restored),
            restore_result.core_memories_restored,
            restore_result.recall_memories_restored,
            restore_result.journal_entries_restored,
            restore_result.relationships_restored,
        )
        if restore_result.warnings:
            for w in restore_result.warnings:
                logger.warning("Snapshot restore warning: %s", w)

    # ── Run ───────────────────────────────────────────────
    if sim_config.mode == "autonomous":
        await orchestrator.run_autonomous()
    else:
        await orchestrator.run()

    # ── Cleanup ───────────────────────────────────────────
    await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a full-day simulation of the AI reality show")
    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="Name for this simulation run",
    )
    parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Description of the simulation",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        default=None,
        help="Path to the YAML seed file defining phases (omit for autonomous mode)",
    )
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        help="Simulated duration for autonomous mode (e.g. '7d', '1d', '12h')",
    )
    parser.add_argument(
        "--duration-hours",
        type=float,
        default=None,
        help="Wall-clock-style duration in hours for embodied Minecraft supervisor runs",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help=(
            "Comma-separated agent names. Defaults to the seed file agents when present; "
            f"otherwise {DEFAULT_AGENTS}."
        ),
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=10.0,
        help="Maximum cost in dollars before stopping (default: 10.00)",
    )
    parser.add_argument(
        "--max-cost-rolling",
        type=float,
        default=None,
        help=("Maximum cost in dollars within --rolling-window before stopping (default: off)"),
    )
    parser.add_argument(
        "--rolling-window",
        type=str,
        default=None,
        help=("Rolling cost window for --max-cost-rolling, e.g. '1h' or '24h' (default: off)"),
    )
    parser.add_argument(
        "--speed",
        type=str,
        choices=["fast", "normal"],
        default="fast",
        help="Simulation speed (fast=skip idle, normal=real pacing)",
    )
    parser.add_argument(
        "--speed-multiplier",
        type=float,
        default=0,
        help=(
            "Simulated clock speed (0=instant/legacy, 42=42x speed, 1=real-time). "
            "For autonomous mode with --duration, use >0 (e.g. 42) so simulated "
            "time advances meaningfully between conversations."
        ),
    )
    parser.add_argument(
        "--management-shadow",
        action="store_true",
        default=None,
        help="Deprecated alias for --management-policy shadow",
    )
    parser.add_argument(
        "--no-management-shadow",
        action="store_false",
        dest="management_shadow",
        help="Deprecated alias for --management-policy enforce",
    )
    parser.add_argument(
        "--management-policy",
        choices=[policy.value for policy in ManagementPolicy],
        default=None,
        help="Management policy for this run: off, shadow, or enforce",
    )
    parser.add_argument(
        "--restore-snapshot",
        type=str,
        default=None,
        help="Path to a memory snapshot JSON file to pre-load before simulation",
    )
    parser.add_argument(
        "--sim-id",
        type=str,
        default=None,
        help=(
            "Attach to a pre-created simulation row (UUID) instead of "
            "inserting a new one. Used by the admin dashboard to redirect "
            "the user to /simulations/<id> immediately on launch."
        ),
    )
    parser.add_argument(
        "--resume-sim-id",
        type=str,
        default=None,
        help=(
            "Resume an existing persistent simulation row after a supervisor "
            "restart. Alias for --sim-id in the persistent restart path."
        ),
    )
    parser.add_argument(
        "--run-config-file",
        type=str,
        default=None,
        help=(
            "Path to a JSON config file with public submission overrides "
            "(agents, exclusions, factions, memory seed, run-spec fields, energy, cadence)."
        ),
    )
    parser.add_argument(
        "--run-mode",
        type=str,
        choices=["persistent", "experimental"],
        default=None,
        help=(
            "Run-mode starting condition. Seeded runs default to experimental; "
            "persistent is only used when explicitly requested."
        ),
    )
    parser.add_argument(
        "--conversation-mode",
        type=str,
        choices=["director", "embodied", "director_v2"],
        default=None,
        help=(
            "Conversation implementation for this run. embodied and director_v2 "
            "use the embodied Minecraft supervisor by default."
        ),
    )
    parser.add_argument(
        "--no-embodied-supervisor",
        action="store_true",
        default=False,
        help="Run the legacy Python orchestrator even when --conversation-mode is embodied",
    )
    parser.add_argument(
        "--minecraft-log-dir",
        type=str,
        default=None,
        help="Evidence directory passed to the embodied Minecraft supervisor",
    )
    parser.add_argument(
        "--no-embodied-eval",
        action="store_true",
        default=False,
        help="Skip the embodied supervisor end-of-run eval hook",
    )
    parser.add_argument(
        "--no-embodied-report",
        action="store_true",
        default=False,
        help="Skip the embodied supervisor end-of-run report hook",
    )
    parser.add_argument(
        "--experimental-goal",
        type=str,
        default=None,
        help=(
            "Goal stop condition for experimental autonomous runs, formatted "
            "as '<kind>:<target>' where kind is turns, artifacts, or phases_complete."
        ),
    )
    parser.add_argument(
        "--persistent",
        action="store_true",
        default=False,
        help="Convenience flag for --run-mode persistent.",
    )
    parser.add_argument(
        "--world-config-file",
        type=str,
        default=None,
        help=(
            "Path to a custom Minecraft world config for this run. Overrides "
            "the run config's world block and records world_type=custom."
        ),
    )
    parser.add_argument(
        "--world-sim",
        action="store_true",
        default=False,
        help="Enable WorldSimulator (simulates social media, email, and world reactions)",
    )
    parser.add_argument(
        "--hypothesis",
        type=str,
        default=None,
        help=(
            "What you expect to happen this run. Stored on the simulation "
            "row so the run can be evaluated as a research artifact."
        ),
    )
    parser.add_argument(
        "--auto-draft-learnings",
        action="store_true",
        default=False,
        help=(
            "After completion, ask an LLM to draft a 2-3 sentence learnings "
            "entry summarizing the run. Off by default."
        ),
    )
    parser.add_argument(
        "--memory-seed-mode",
        type=str,
        choices=["none", "inherit", "custom"],
        default=None,
        help=(
            "Override the scenario's memory_seed block. 'none' wipes all "
            "agent memory; 'inherit' copies from --memory-seed-inherit-from; "
            "'custom' loads --memory-seed-file."
        ),
    )
    parser.add_argument(
        "--memory-seed-file",
        type=str,
        default=None,
        help=(
            "Path to a JSON/YAML snapshot file mapping agent_id to "
            "core_memory + recall entries. Required when "
            "--memory-seed-mode=custom."
        ),
    )
    parser.add_argument(
        "--memory-seed-inherit-from",
        type=str,
        default=None,
        help=(
            "Source simulation UUID to copy core + recall memory from. "
            "Required when --memory-seed-mode=inherit."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would execute without making LLM calls",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    if args.persistent:
        if args.run_mode and args.run_mode != "persistent":
            parser.error("--persistent cannot be combined with --run-mode experimental")
        args.run_mode = "persistent"
    if args.experimental_goal and args.run_mode is None:
        args.run_mode = "experimental"
    if args.resume_sim_id and args.sim_id and args.resume_sim_id != args.sim_id:
        parser.error("--resume-sim-id and --sim-id must match when both are provided")
    if args.duration and args.duration_hours is not None:
        parser.error("--duration and --duration-hours are mutually exclusive")
    if args.duration_hours is not None and args.duration_hours <= 0:
        parser.error("--duration-hours must be greater than zero")
    if args.run_mode == "persistent" and (args.duration or args.duration_hours is not None):
        parser.error("persistent mode is indefinite; do not set --duration")
    if args.run_mode == "persistent" and args.experimental_goal:
        parser.error("persistent mode is indefinite; do not set --experimental-goal")
    if args.run_mode == "experimental" and args.resume_sim_id:
        parser.error("experimental mode starts fresh; do not set --resume-sim-id")
    if (
        args.run_mode == "experimental"
        and not args.seed_file
        and not args.duration
        and args.duration_hours is None
        and not args.experimental_goal
    ):
        parser.error(
            "experimental mode requires --seed-file, --duration, --duration-hours, or --experimental-goal"
        )
    if (
        not args.seed_file
        and not args.duration
        and args.duration_hours is None
        and not args.experimental_goal
        and args.run_mode != "persistent"
    ):
        parser.error(
            "Either --seed-file, --duration, --duration-hours, or --experimental-goal must be provided"
        )
    if (args.max_cost_rolling is None) != (args.rolling_window is None):
        parser.error("--max-cost-rolling and --rolling-window must be provided together")
    if args.max_cost_rolling is not None and args.max_cost_rolling < 0:
        parser.error("--max-cost-rolling cannot be negative")
    if args.run_mode == "persistent" and (
        args.max_cost_rolling is None or args.rolling_window is None
    ):
        print(
            "WARNING: persistent mode requires --max-cost-rolling and --rolling-window; "
            "SimulationConfig will reject this run.",
            file=sys.stderr,
        )

    # Warn about instant-mode + duration: in instant mode (speed_multiplier=0),
    # simulated time only advances by wall-clock conversation duration, so a
    # --duration of "7d" would take an extremely long time to reach. Recommend
    # using a speed multiplier (e.g. --speed-multiplier 42) for autonomous runs.
    if (
        (args.duration or args.duration_hours is not None)
        and args.speed_multiplier == 0
        and not args.seed_file
    ):
        print(
            "\n  WARNING: --duration with --speed-multiplier 0 (instant mode)"
            "\n  will advance simulated time very slowly. Each conversation only"
            "\n  adds its wall-clock duration to the simulated clock."
            "\n  Recommend: --speed-multiplier 42 (or higher) for autonomous runs.\n"
        )

    asyncio.run(run_simulation(args))


if __name__ == "__main__":
    main()
