"""Conversation inspection endpoints.

Provides conversation detail, turns, selection logs, management flags,
artifacts, and interrupts.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from core.admin.dependencies import get_db
from core.models import (
    ConversationDetail,
    SelectionLog,
    TurnDetail,
)

if TYPE_CHECKING:
    from core.database import Database

router = APIRouter(tags=["conversations"])


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> ConversationDetail:
    """Full conversation: transcript, participants, trigger, energy history."""
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.transcript_repo import TranscriptRepo

    conv_repo = ConversationRepo(db)
    transcript_repo = TranscriptRepo(db)

    conv = await conv_repo.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    energy_log = await conv_repo.get_energy_log(conv_id)
    transcript_record = await transcript_repo.get_by_conversation(conv_id)

    transcript_text = transcript_record.content if transcript_record else ""
    total_tokens = len(transcript_text) // 4 if transcript_text else 0

    return ConversationDetail(
        id=conv.id,
        simulation_id=conv.simulation_id,
        started_at=conv.started_at,
        ended_at=conv.ended_at,
        trigger_type=conv.trigger_type,
        trigger_details=conv.trigger_details,
        initial_energy=conv.initial_energy,
        final_energy=conv.final_energy,
        turn_count=conv.turn_count,
        participating_agents=conv.participating_agents,
        topics_discussed=conv.topics_discussed,
        closed_by=conv.closed_by,
        location=conv.location,
        energy_history=energy_log,
        transcript=transcript_record.content if transcript_record else None,
        total_tokens=total_tokens,
        total_cost="0",
    )


@router.get("/conversations/{conv_id}/turns", response_model=list[TurnDetail])
async def get_conversation_turns(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[TurnDetail]:
    """Turn-by-turn detail with selection scores."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    logs = await conv_repo.get_selection_log(conv_id)
    return [
        TurnDetail(
            turn_number=log.turn_number,
            selected_agent_id=log.selected_agent_id,
            was_interrupt=log.was_interrupt,
            agent_scores=log.agent_scores,
            detected_topic=log.detected_topic,
            previous_speaker_id=log.previous_speaker_id,
            conversation_energy=log.conversation_energy,
            timestamp=log.timestamp,
        )
        for log in logs
    ]


@router.get("/conversations/{conv_id}/selection-log", response_model=list[SelectionLog])
async def get_conversation_selection_log(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[SelectionLog]:
    """Speaker selection scores for every turn (all candidates scored)."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    return await conv_repo.get_selection_log(conv_id)


@router.get("/conversations/{conv_id}/management-flags")
async def get_conversation_management_flags(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Management shadow flags for this conversation."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    return await conv_repo.get_management_flags(conv_id)


@router.get("/conversations/{conv_id}/artifacts")
async def get_conversation_artifacts(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Tool invocation artifacts for this conversation."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    return await conv_repo.get_artifacts(conv_id)


@router.get("/conversations/{conv_id}/interrupts")
async def get_conversation_interrupts(
    conv_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Interrupt events for this conversation."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    return await conv_repo.get_interrupts(conv_id)
