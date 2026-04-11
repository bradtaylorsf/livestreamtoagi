#!/usr/bin/env python3
"""Seed versioned agent config from YAML files into the database.

Reads agents/{id}/config.yaml, system_prompt.md, and behaviors.yaml
and inserts them as version 1 with source='seed'. Also seeds
conversation_config.yaml as conversation_param_versions version 1.

Idempotent: skips agents/params that already have version 1.

Usage:
    pnpm chat seed-config
    python scripts/seed_config.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from rich.console import Console

from core.constants import LIVE_SIMULATION_ID

console = Console()
logger = logging.getLogger(__name__)


async def seed_agent_configs() -> None:
    """Read YAML files and insert as version 1 in the database."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.config_version_repo import ConfigVersionRepo

    services = await bootstrap_services(auto_migrate=True)
    try:
        assert services.db is not None
        config_repo = ConfigVersionRepo(services.db)
        agents_dir = PROJECT_ROOT / "agents"

        if not agents_dir.is_dir():
            console.print("[red]agents/ directory not found[/red]")
            return

        seeded_agents = 0
        skipped_agents = 0

        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            config_path = agent_dir / "config.yaml"
            if not config_path.exists():
                continue

            agent_id = agent_dir.name

            # Check if version 1 already exists
            existing = await config_repo.get_prompt_version(agent_id, 1, simulation_id=LIVE_SIMULATION_ID)
            if existing is not None:
                console.print(f"  [dim]Skipping {agent_id} (version 1 exists)[/dim]")
                skipped_agents += 1
                continue

            # Load config.yaml
            with open(config_path, encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}

            # Load system_prompt.md
            prompt_path = agent_dir / "system_prompt.md"
            system_prompt = ""
            if prompt_path.exists():
                system_prompt = prompt_path.read_text(encoding="utf-8")

            # Load behaviors.yaml
            behaviors: dict = {}
            behaviors_path = agent_dir / "behaviors.yaml"
            if behaviors_path.exists():
                with open(behaviors_path, encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        behaviors = loaded

            # Build config_params from numeric/string fields in config.yaml
            config_params = {}
            param_keys = [
                "chattiness", "initiative", "interrupt_tendency",
                "eavesdrop_tendency", "closing_weight", "voice_id",
                "model_conversation", "model_building", "display_name",
            ]
            for key in param_keys:
                if key in raw_config:
                    config_params[key] = raw_config[key]

            # Insert version 1
            version = await config_repo.insert_prompt_version(
                agent_id,
                system_prompt=system_prompt,
                behaviors=behaviors,
                config_params=config_params,
                change_reason="Initial seed from YAML files",
                source="seed",
                simulation_id=LIVE_SIMULATION_ID,
            )

            # Set as active
            await config_repo.set_active_prompt_version(agent_id, version.version, simulation_id=LIVE_SIMULATION_ID)

            console.print(f"  [green]Seeded {agent_id} v{version.version}[/green]")
            seeded_agents += 1

        # Seed conversation params
        config_path = PROJECT_ROOT / "config" / "conversation_config.yaml"
        if config_path.exists():
            existing_params = await config_repo.get_conversation_param_version(1, simulation_id=LIVE_SIMULATION_ID)
            if existing_params is not None:
                console.print("  [dim]Skipping conversation params (version 1 exists)[/dim]")
            else:
                with open(config_path, encoding="utf-8") as f:
                    raw_params = yaml.safe_load(f) or {}

                version = await config_repo.insert_conversation_param_version(
                    params=raw_params,
                    change_reason="Initial seed from conversation_config.yaml",
                    source="seed",
                    simulation_id=LIVE_SIMULATION_ID,
                )
                await config_repo.set_active_conversation_version(version.version, simulation_id=LIVE_SIMULATION_ID)
                console.print(f"  [green]Seeded conversation params v{version.version}[/green]")

        console.print(
            f"\n[bold]Done: {seeded_agents} agents seeded, "
            f"{skipped_agents} skipped.[/bold]"
        )
    finally:
        await shutdown_services(services)


def main() -> None:
    console.print("\n[bold bright_cyan]Seeding versioned agent config...[/bold bright_cyan]\n")
    asyncio.run(seed_agent_configs())


if __name__ == "__main__":
    main()
