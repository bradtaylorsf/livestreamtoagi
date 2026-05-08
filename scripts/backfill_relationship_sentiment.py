#!/usr/bin/env python3
"""Backfill sentiment_score / trust_score on agent_relationships.

Earlier versions of RelationshipTracker only persisted sentiment + trust
when the LLM returned a row for that pair. Pairs the LLM omitted (one-sided
exchanges, silent participants, malformed JSON) kept NULL forever, so the
social graph table on /simulations/[id]?tab=social-graph showed "—" for
the columns.

This script finds completed simulations whose relationships still have
NULL sentiment_score or trust_score, replays the conversations through
RelationshipTracker._extract_and_update_sentiment to fill them in, and
falls back to conservative defaults (sentiment=0.0, trust=0.5) when no
conversations are recoverable.

Usage:
    python scripts/backfill_relationship_sentiment.py
    python scripts/backfill_relationship_sentiment.py --dry-run
    python scripts/backfill_relationship_sentiment.py --simulation-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def _backfill_simulation(
    svc: object,
    simulation_id: uuid.UUID,
    *,
    dry_run: bool,
) -> int:
    """Fill missing sentiment/trust for one simulation. Returns rows touched."""
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.relationship_repo import RelationshipRepo
    from core.social.relationship_tracker import RelationshipTracker

    rel_repo = RelationshipRepo(svc.db)  # type: ignore[attr-defined]
    conv_repo = ConversationRepo(svc.db)  # type: ignore[attr-defined]

    missing = await rel_repo.get_relationships_missing_sentiment(simulation_id)
    if not missing:
        return 0

    print(f"  {simulation_id}: {len(missing)} relationship rows missing sentiment/trust")

    if dry_run:
        return len(missing)

    # Pull the simulation's conversations and replay them through the tracker.
    # We use a pagination loop in case the simulation has many conversations.
    conversations: list[object] = []
    offset = 0
    while True:
        page, total = await conv_repo.get_conversations_by_simulation(
            simulation_id, limit=100, offset=offset
        )
        conversations.extend(page)
        if len(conversations) >= total or not page:
            break
        offset += len(page)

    tracker = RelationshipTracker(
        llm_client=svc.llm_client,  # type: ignore[attr-defined]
        relationship_repo=rel_repo,
        simulation_id=simulation_id,
    )

    replayed = 0
    for conv in conversations:
        participants = list(getattr(conv, "participating_agents", []) or [])
        transcript = getattr(conv, "transcript", None) or ""
        if len(participants) < 2:
            continue
        # Build a coarse history list. The transcript is a flat string so we
        # split per-line; speaker is unknown for legacy rows. The LLM still
        # gets the participants list and the raw text.
        history = [
            {"speaker": "unknown", "content": line}
            for line in transcript.splitlines()
            if line.strip()
        ]
        if not history:
            history = [{"speaker": "unknown", "content": transcript}]
        try:
            await tracker.update_after_conversation(history, participants)
            replayed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    replay failed for conversation {conv.id}: {exc}")

    # Even if no conversations were recoverable, fill remaining NULL rows
    # with the conservative defaults so the table no longer shows "—".
    still_missing = await rel_repo.get_relationships_missing_sentiment(simulation_id)
    for rel in still_missing:
        await rel_repo.upsert(
            simulation_id,
            rel.agent_id,
            rel.target_agent_id,
            sentiment_score=0.0,
            trust_score=0.5,
        )

    print(
        f"    replayed {replayed} conversation(s); "
        f"default-filled {len(still_missing)} row(s)"
    )
    return len(missing)


async def run_backfill(*, dry_run: bool, simulation_id: uuid.UUID | None) -> int:
    from core.bootstrap import bootstrap_services, shutdown_services

    svc = await bootstrap_services(auto_migrate=True)
    try:
        if simulation_id is not None:
            sim_ids = [simulation_id]
        else:
            rows = await svc.db.fetch(
                """SELECT DISTINCT simulation_id
                   FROM agent_relationships
                   WHERE simulation_id IS NOT NULL
                     AND (sentiment_score IS NULL OR trust_score IS NULL)""",
            )
            sim_ids = [r["simulation_id"] for r in rows]

        print(f"Simulations needing backfill: {len(sim_ids)}")
        total = 0
        for sid in sim_ids:
            total += await _backfill_simulation(svc, sid, dry_run=dry_run)

        if dry_run:
            print(f"Dry run — would backfill {total} relationship row(s).")
        else:
            print(f"Backfill complete. Touched {total} relationship row(s).")
        return total
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--simulation-id",
        type=str,
        default=None,
        help="Only backfill the named simulation (UUID).",
    )
    args = parser.parse_args()
    sim_id = uuid.UUID(args.simulation_id) if args.simulation_id else None
    asyncio.run(run_backfill(dry_run=args.dry_run, simulation_id=sim_id))


if __name__ == "__main__":
    main()
