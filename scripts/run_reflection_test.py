#!/usr/bin/env python3
"""Directly run 6-hour reflection + dream cycle for all agents.

Usage:
    .venv/bin/python scripts/run_reflection_test.py

Tests:
  1. 6-hour reflection parses cleanly (no JSON truncation)
  2. Dream cycle completes and produces goals + journal entries
  3. Reports pass/fail per agent
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
# Show our reflection + dream logs
logging.getLogger("core.memory.reflection").setLevel(logging.INFO)
logging.getLogger("core.memory.dreams").setLevel(logging.INFO)

AGENTS = ["vera", "rex", "aurora", "fork", "sentinel", "pixel", "grok"]


async def main() -> None:
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.memory.reflection import ReflectionManager

    print("Bootstrapping services...")
    svc = await bootstrap_services(auto_migrate=True)

    reflection_mgr = ReflectionManager(
        memory_repo=svc.memory_repo,
        llm_client=svc.llm_client,
        core_memory_mgr=svc.core_memory,
        token_counter=svc.token_counter,
        agent_registry=svc.agent_registry,
        goal_manager=svc.goal_manager,
        agent_state_manager=svc.agent_state_manager,
        dream_manager=svc.dream_manager,
    )

    reflection_results: dict[str, str] = {}
    dream_results: dict[str, str] = {}

    # ── 6-hour reflections ────────────────────────────────────────
    print(f"\n{'='*60}")
    print("PHASE 1: 6-hour reflections")
    print('='*60)

    for agent_id in AGENTS:
        print(f"\n  [{agent_id}] running reflection...", end=" ", flush=True)
        try:
            result = await reflection_mgr.run_6hour_reflection(agent_id)
            if result.journal_entry:
                snippet = result.journal_entry.content[:80].replace("\n", " ")
                print(f"OK — journal: \"{snippet}...\"")
                reflection_results[agent_id] = "PASS"
            else:
                print("OK (no journal entry — no memories)")
                reflection_results[agent_id] = "PASS (no memories)"
        except Exception as exc:
            print(f"FAIL — {exc}")
            reflection_results[agent_id] = f"FAIL: {exc}"

    # ── Dream cycles ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("PHASE 2: Dream cycles")
    print('='*60)

    for agent_id in AGENTS:
        print(f"\n  [{agent_id}] dreaming...", end=" ", flush=True)
        try:
            dream = await svc.dream_manager.run_dream(agent_id)
            if dream is None:
                print("FAIL — run_dream returned None")
                dream_results[agent_id] = "FAIL: returned None"
                continue

            goals_str = f"{len(dream.new_goals)} goal(s)" if dream.new_goals else "0 goals"
            insights_str = f"{len(dream.insights)} insight(s)"
            mood_str = dream.mood_shift
            narrative_snippet = dream.dream_narrative[:60].replace("\n", " ")
            print(f"OK — {goals_str}, {insights_str}, mood={mood_str}")
            print(f"         narrative: \"{narrative_snippet}...\"")

            if dream.new_goals:
                for g in dream.new_goals:
                    print(f"         goal [{g.category}]: {g.description[:70]}")

            dream_results[agent_id] = "PASS"
        except Exception as exc:
            print(f"FAIL — {exc}")
            dream_results[agent_id] = f"FAIL: {exc}"

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    print("\nReflection:")
    for agent, status in reflection_results.items():
        icon = "✓" if status.startswith("PASS") else "✗"
        print(f"  {icon} {agent:12s} {status}")

    print("\nDreams:")
    for agent, status in dream_results.items():
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} {agent:12s} {status}")

    # Verify goals in DB
    print("\nGoals written to DB (source='dream'):")
    try:
        from datetime import UTC, datetime, timedelta
        since = datetime.now(UTC) - timedelta(hours=1)
        rows = await svc.db.fetch(
            "SELECT agent_id, goal FROM agent_goals WHERE source = 'dream' AND created_at >= $1 ORDER BY agent_id",
            since,
        )
        if rows:
            for row in rows:
                print(f"  ✓ [{row['agent_id']}] {row['goal'][:80]}")
        else:
            print("  ✗ No dream goals found in last hour — check migration 030 was applied")
    except Exception as exc:
        print(f"  ✗ DB check failed: {exc}")

    await shutdown_services(svc)


if __name__ == "__main__":
    asyncio.run(main())
