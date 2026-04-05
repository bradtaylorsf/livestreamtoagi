"""Shared fixtures for integration tests.

Provides bootstrapped Services, DB cleanup, httpx test client,
and a simulation runner that executes once per module.

Requires Docker Compose services to be running.
Run with: pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://agi:devpassword@localhost:5434/livestream_agi_test"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6381")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def services():
    """Bootstrap all services with auto-migration against the test DB."""
    # Point bootstrap at test database
    os.environ["DATABASE_URL"] = DATABASE_URL
    os.environ["REDIS_URL"] = REDIS_URL

    from core.bootstrap import bootstrap_services, init_core_memories, shutdown_services

    svc = await bootstrap_services(auto_migrate=True)

    # Initialize core memories for all agents (same as app startup)
    if svc.core_memory:
        await init_core_memories(svc.agent_registry, svc.core_memory)

    yield svc

    # Clean up data created during integration tests so we don't pollute
    # the shared test database for subsequent test runs.
    if svc.db:
        await svc.db.execute("DELETE FROM management_shadow_log")
        await svc.db.execute("DELETE FROM journal_entries WHERE reflection_type = 'conversation'")
        await svc.db.execute("DELETE FROM recall_memory")
        await svc.db.execute("DELETE FROM artifacts")
        await svc.db.execute("DELETE FROM cost_events")
        await svc.db.execute("DELETE FROM energy_change_log")
        await svc.db.execute("DELETE FROM conversation_selection_log")
        await svc.db.execute("DELETE FROM transcripts")
        await svc.db.execute("DELETE FROM conversations")
        await svc.db.execute("DELETE FROM simulations")

    await shutdown_services(svc)


@pytest.fixture(scope="module")
def start_time():
    """Timestamp before the simulation starts — used to filter newly created rows."""
    return datetime.now(UTC)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def simulation_result(services, start_time):
    """Run a minimal simulation (2 agents, 1 organic phase, max 3 turns).

    Returns (simulation_id, conversation_ids) for downstream test stages.
    """
    import tempfile

    import yaml

    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import EventBus
    from core.memory.reflection import ReflectionManager
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.display import SimulationDisplay
    from core.simulation.orchestrator import SimulationConfig, SimulationOrchestrator

    svc = services
    agents = ["rex", "fork"]

    # Write a minimal seed YAML
    seed = {
        "phases": [
            {
                "name": "qa_organic",
                "type": "organic",
                "max_turns": 3,
                "count": 1,
            },
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(seed, f)
        seed_path = f.name

    sim_config = SimulationConfig(
        name="qa-pipeline-test",
        description="Automated QA pipeline validation",
        seed_file=seed_path,
        agents=agents,
        max_cost=5.0,
        speed="fast",
        dry_run=False,
        verbose=False,
        management_shadow=True,
    )
    sim_config.load_seed_file()

    cfg = svc.config_loader.config
    event_bus = EventBus()
    conversation_repo = ConversationRepo(svc.db)
    simulation_repo = SimulationRepo(svc.db)

    from core.management import Management

    management = Management(
        redis_client=svc.redis,
        llm_client=svc.llm_client,
        event_bus=event_bus,
        shadow_mode=True,
        db=svc.db,
    )

    proximity = ProximityManager(svc.redis, cfg, event_bus)
    trigger_system = TriggerSystem(cfg.triggers, recall_memory=svc.recall_memory)
    selection_logger = SelectionLogger(conversation_repo, cfg.logging)

    reflection_manager = ReflectionManager(
        memory_repo=svc.memory_repo,
        llm_client=svc.llm_client,
        core_memory_mgr=svc.core_memory,
        token_counter=svc.token_counter,
        agent_registry=svc.agent_registry,
    )

    display = SimulationDisplay(verbose=False)

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
    )

    await orchestrator.run()

    sim_id = orchestrator.simulation_id
    assert sim_id is not None, "Simulation ID should be set after run"

    # Fetch conversation IDs
    rows = await svc.db.fetch(
        "SELECT id FROM conversations WHERE simulation_id = $1", sim_id
    )
    conversation_ids = [row["id"] for row in rows]

    # Clean up temp file
    os.unlink(seed_path)

    return {
        "simulation_id": sim_id,
        "conversation_ids": conversation_ids,
        "agents": agents,
        "start_time": start_time,
    }
