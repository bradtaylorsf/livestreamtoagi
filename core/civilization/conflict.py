"""Persistent conflict ledger for the civilization MVP (issue #895).

Conflict is the fifth and final civilization mechanic after ownership
(#891), trade (#892), theft (#893), and diplomacy (#894). It resolves
disputes that grow out of the prior layers — territorial claims, theft
fallout, broken treaties, trade breaches, personal grievances — and
escalates them through judgement, surrender, or outright war.

The ledger supports two top-level entities:

* :class:`Dispute` — a single grievance between two agents. Lifecycle:
  ``open → judged → resolved`` (or ``→ escalated`` to war when the
  losing party refuses the judgement).
* :class:`WarIntent` — escalation between two factions. Requires a
  majority of the initiator faction's members to second the call before
  it activates. Stays active until surrender or arbitration.

Judgement is deterministic: same ``simulation_id + dispute_id`` seed plus
the same evidence list always yields the same ruling. Evidence with more
``ref_type`` entries that can be cross-referenced against the prior logs
weighs more heavily than free-form narratives, so an agent can't win a
dispute by spamming uncited claims.

Persistence is append-only JSONL at ``<sim_folder>/conflict_log.jsonl``.
The ledger replays the file on construction so resumed sims inherit
open disputes, active wars, and resolved outcomes without bespoke
migration code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_CONFLICT_LOG_FILENAME = "conflict_log.jsonl"

DisputeType = Literal[
    "territorial",
    "theft",
    "trade_breach",
    "treaty_violation",
    "personal",
]
DisputeStatus = Literal["open", "judged", "resolved", "escalated"]
WarStatus = Literal["pending", "active", "resolved"]
ConflictAction = Literal[
    "opened",
    "evidence_submitted",
    "judged",
    "resolved",
    "escalated",
    "war_declared",
    "war_seconded",
    "war_activated",
    "surrendered",
]
ConflictFailureReason = Literal[
    "unknown_dispute",
    "unknown_war",
    "self_dispute",
    "duplicate_evidence",
    "not_a_party",
    "not_open",
    "already_judged",
    "not_active",
    "agent_not_in_faction",
    "no_quorum",
    "invalid_type",
]

_VALID_DISPUTE_TYPES = frozenset(
    {"territorial", "theft", "trade_breach", "treaty_violation", "personal"}
)
_DEFAULT_TRUST = 0.5
_WAR_TICK_TRUST_HIT = 0.1
_PERSONAL_LOSER_TRUST_HIT = 0.2
_THEFT_LOSER_TRUST_HIT = 0.3


class EvidenceRef(BaseModel):
    """A single piece of evidence attached to a dispute."""

    model_config = ConfigDict(extra="forbid")

    ref_type: Literal["theft", "trade", "ownership", "diplomacy", "utterance"]
    ref_id: str
    narrative: str | None = None
    submitter_id: str | None = None


class Dispute(BaseModel):
    """A pairwise grievance — append-only once opened."""

    model_config = ConfigDict(extra="forbid")

    dispute_id: str
    initiator_id: str
    respondent_id: str
    dispute_type: DisputeType
    evidence: list[EvidenceRef] = Field(default_factory=list)
    status: DisputeStatus = "open"
    motivation: str | None = None
    judgement: str | None = None
    outcome: dict[str, Any] | None = None
    created_at: datetime
    judged_at: datetime | None = None
    resolved_at: datetime | None = None


class WarIntent(BaseModel):
    """A war declared by one faction against another (needs quorum to activate)."""

    model_config = ConfigDict(extra="forbid")

    war_id: str
    initiator_id: str
    initiator_faction_id: str
    target_faction_id: str
    casus_belli: str
    motivation: str | None = None
    seconders: set[str] = Field(default_factory=set)
    required_quorum: int
    status: WarStatus = "pending"
    created_at: datetime
    activated_at: datetime | None = None
    resolved_at: datetime | None = None
    surrender_terms: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConflictFailure:
    """Returned when a conflict action cannot proceed."""

    status: Literal["error"] = "error"
    reason: ConflictFailureReason = "unknown_dispute"
    dispute_id: str | None = None
    war_id: str | None = None
    detail: str | None = None


def _normalize_evidence(
    entries: list[Any] | None,
    *,
    submitter_id: str | None = None,
) -> list[EvidenceRef]:
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ValueError("evidence must be a list of objects")
    out: list[EvidenceRef] = []
    for entry in entries:
        if isinstance(entry, EvidenceRef):
            out.append(entry)
            continue
        if not isinstance(entry, dict):
            raise ValueError("evidence entries must be objects")
        ref_type = entry.get("ref_type")
        ref_id = entry.get("ref_id")
        narrative = entry.get("narrative")
        if not isinstance(ref_type, str) or ref_type not in {
            "theft",
            "trade",
            "ownership",
            "diplomacy",
            "utterance",
        }:
            raise ValueError(
                "evidence ref_type must be one of theft/trade/ownership/diplomacy/utterance"
            )
        if not isinstance(ref_id, str) or not ref_id:
            raise ValueError("evidence ref_id must be a non-empty string")
        out.append(
            EvidenceRef(
                ref_type=ref_type,  # type: ignore[arg-type]
                ref_id=ref_id,
                narrative=(
                    narrative.strip() if isinstance(narrative, str) and narrative.strip() else None
                ),
                submitter_id=submitter_id,
            )
        )
    return out


def _deterministic_score(simulation_id: str, dispute_id: str, salt: str) -> float:
    """Hash (simulation_id, dispute_id, salt) → float in [0, 1)."""
    blob = f"{simulation_id}|{dispute_id}|{salt}".encode()
    digest = hashlib.sha256(blob).digest()
    n = int.from_bytes(digest[:8], "big")
    return n / (1 << 64)


def _ref_supported(ref: EvidenceRef, *, support_index: dict[str, set[str]]) -> bool:
    """True iff the evidence ref can be cross-referenced against a known log id."""
    known = support_index.get(ref.ref_type)
    if not known:
        return False
    return ref.ref_id in known


class ConflictLedger:
    """In-memory dispute + war index with append-only JSONL persistence.

    The ledger holds references to its sibling ledgers (ownership, trade,
    theft, diplomacy) so that the consequence routing for each
    ``dispute_type`` lands in the right subsystem without the caller
    having to wire it manually:

    * ``territorial`` — ownership transfer via the ownership ledger.
    * ``theft`` — restitution trade offer via the trade ledger.
    * ``treaty_violation`` — treaty break via the diplomacy ledger.
    * ``trade_breach`` — relationship delta only (the trade ledger
      already records the broken offer chain).
    * ``personal`` — relationship delta only.
    """

    def __init__(
        self,
        sim_folder: str | Path | None,
        *,
        simulation_id: str | uuid.UUID | None = None,
        diplomacy_ledger: Any | None = None,
        ownership_ledger: Any | None = None,
        trade_ledger: Any | None = None,
        theft_ledger: Any | None = None,
    ) -> None:
        self._sim_folder: Path | None = Path(sim_folder) if sim_folder is not None else None
        self._path: Path | None = None
        if self._sim_folder is not None:
            self._sim_folder.mkdir(parents=True, exist_ok=True)
            self._path = self._sim_folder / _CONFLICT_LOG_FILENAME

        self._simulation_id = str(simulation_id) if simulation_id is not None else ""
        self._diplomacy_ledger = diplomacy_ledger
        self._ownership_ledger = ownership_ledger
        self._trade_ledger = trade_ledger
        self._theft_ledger = theft_ledger

        self._disputes: dict[str, Dispute] = {}
        self._wars: dict[str, WarIntent] = {}

        self._replay()

    # ─── Public properties ─────────────────────────────────────────────

    @property
    def path(self) -> Path | None:
        return self._path

    def get_dispute(self, dispute_id: str) -> Dispute | None:
        return self._disputes.get(dispute_id)

    def get_war(self, war_id: str) -> WarIntent | None:
        return self._wars.get(war_id)

    def all_disputes(self) -> list[Dispute]:
        return list(self._disputes.values())

    def active_wars(self) -> list[WarIntent]:
        return [w for w in self._wars.values() if w.status == "active"]

    def all_wars(self) -> list[WarIntent]:
        return list(self._wars.values())

    # ─── Mutating API ──────────────────────────────────────────────────

    def open_dispute(
        self,
        *,
        initiator_id: str,
        respondent_id: str,
        dispute_type: str,
        evidence_refs: list[Any] | None = None,
        motivation: str | None = None,
    ) -> Dispute | ConflictFailure:
        if initiator_id == respondent_id:
            return ConflictFailure(
                reason="self_dispute",
                detail="cannot open a dispute against yourself",
            )
        if dispute_type not in _VALID_DISPUTE_TYPES:
            return ConflictFailure(
                reason="invalid_type",
                detail=f"dispute_type must be one of {sorted(_VALID_DISPUTE_TYPES)}",
            )
        try:
            evidence = _normalize_evidence(evidence_refs, submitter_id=initiator_id)
        except ValueError as exc:
            return ConflictFailure(reason="duplicate_evidence", detail=str(exc))

        dispute = Dispute(
            dispute_id=str(uuid.uuid4()),
            initiator_id=initiator_id,
            respondent_id=respondent_id,
            dispute_type=dispute_type,  # type: ignore[arg-type]
            evidence=evidence,
            status="open",
            motivation=(
                motivation.strip() if isinstance(motivation, str) and motivation.strip() else None
            ),
            created_at=datetime.now(UTC),
        )
        self._disputes[dispute.dispute_id] = dispute
        self._append_event(
            {
                "action": "opened",
                "dispute_id": dispute.dispute_id,
                "initiator_id": dispute.initiator_id,
                "respondent_id": dispute.respondent_id,
                "dispute_type": dispute.dispute_type,
                "evidence": [e.model_dump() for e in dispute.evidence],
                "motivation": dispute.motivation,
                "wall_time": dispute.created_at.isoformat(),
            }
        )
        return dispute

    def submit_evidence(
        self,
        dispute_id: str,
        *,
        submitter_id: str,
        evidence_ref: dict[str, Any],
        narrative: str | None = None,
    ) -> Dispute | ConflictFailure:
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            return ConflictFailure(reason="unknown_dispute", dispute_id=dispute_id)
        if dispute.status != "open":
            return ConflictFailure(
                reason="not_open",
                dispute_id=dispute_id,
                detail=f"status={dispute.status}",
            )
        if submitter_id not in (dispute.initiator_id, dispute.respondent_id):
            return ConflictFailure(
                reason="not_a_party",
                dispute_id=dispute_id,
                detail=f"{submitter_id!r} is not a party to this dispute",
            )
        merged = dict(evidence_ref or {})
        if isinstance(narrative, str) and narrative.strip():
            merged["narrative"] = narrative.strip()
        try:
            new_entries = _normalize_evidence([merged], submitter_id=submitter_id)
        except ValueError as exc:
            return ConflictFailure(
                reason="duplicate_evidence",
                dispute_id=dispute_id,
                detail=str(exc),
            )
        entry = new_entries[0]
        existing_keys = {(e.ref_type, e.ref_id) for e in dispute.evidence}
        if (entry.ref_type, entry.ref_id) in existing_keys:
            return ConflictFailure(
                reason="duplicate_evidence",
                dispute_id=dispute_id,
                detail=f"evidence {entry.ref_type}:{entry.ref_id} already attached",
            )
        updated = dispute.model_copy(update={"evidence": [*dispute.evidence, entry]})
        self._disputes[dispute_id] = updated
        self._append_event(
            {
                "action": "evidence_submitted",
                "dispute_id": dispute_id,
                "initiator_id": dispute.initiator_id,
                "respondent_id": dispute.respondent_id,
                "dispute_type": dispute.dispute_type,
                "evidence_entry": entry.model_dump(),
                "submitter_id": submitter_id,
                "wall_time": datetime.now(UTC).isoformat(),
            }
        )
        return updated

    def request_judgement(
        self,
        dispute_id: str,
        *,
        judge_id: str | None = None,
    ) -> Dispute | ConflictFailure:
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            return ConflictFailure(reason="unknown_dispute", dispute_id=dispute_id)
        if dispute.status == "judged" or dispute.status == "resolved":
            return ConflictFailure(
                reason="already_judged",
                dispute_id=dispute_id,
                detail=f"status={dispute.status}",
            )
        if dispute.status != "open":
            return ConflictFailure(
                reason="not_open",
                dispute_id=dispute_id,
                detail=f"status={dispute.status}",
            )

        winner_id, judgement = self._auto_judge(dispute)
        loser_id = (
            dispute.respondent_id if winner_id == dispute.initiator_id else dispute.initiator_id
        )
        outcome: dict[str, Any] = {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "judge_id": judge_id,
        }
        judged_at = datetime.now(UTC)
        updated = dispute.model_copy(
            update={
                "status": "judged",
                "judgement": judgement,
                "outcome": outcome,
                "judged_at": judged_at,
            }
        )
        self._disputes[dispute_id] = updated
        self._append_event(
            {
                "action": "judged",
                "dispute_id": dispute_id,
                "initiator_id": dispute.initiator_id,
                "respondent_id": dispute.respondent_id,
                "dispute_type": dispute.dispute_type,
                "judgement": judgement,
                "outcome": outcome,
                "judge_id": judge_id,
                "wall_time": judged_at.isoformat(),
            }
        )
        return updated

    def accept_judgement(
        self,
        dispute_id: str,
        *,
        accepting_agent_id: str,
        accept: bool,
    ) -> tuple[Dispute, list[dict[str, Any]]] | ConflictFailure:
        """Resolve the dispute when the loser accepts, otherwise escalate it.

        Returns ``(updated_dispute, consequences)`` on success.
        ``consequences`` is a list of side-effect summaries for the caller
        to mirror into the decision log (relationship deltas, treaty
        breaks, ownership transfers, restitution offers).
        """
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            return ConflictFailure(reason="unknown_dispute", dispute_id=dispute_id)
        if dispute.status != "judged":
            return ConflictFailure(
                reason="not_open" if dispute.status == "open" else "already_judged",
                dispute_id=dispute_id,
                detail=f"status={dispute.status}",
            )
        outcome = dispute.outcome or {}
        loser_id = outcome.get("loser_id")
        if accepting_agent_id != loser_id:
            return ConflictFailure(
                reason="not_a_party",
                dispute_id=dispute_id,
                detail=(f"only the losing party ({loser_id!r}) may accept or escalate"),
            )

        resolved_at = datetime.now(UTC)
        if not accept:
            escalated = dispute.model_copy(
                update={
                    "status": "escalated",
                    "resolved_at": resolved_at,
                }
            )
            self._disputes[dispute_id] = escalated
            self._append_event(
                {
                    "action": "escalated",
                    "dispute_id": dispute_id,
                    "initiator_id": dispute.initiator_id,
                    "respondent_id": dispute.respondent_id,
                    "dispute_type": dispute.dispute_type,
                    "judgement": dispute.judgement,
                    "outcome": outcome,
                    "wall_time": resolved_at.isoformat(),
                }
            )
            return escalated, []

        consequences = self._apply_consequences(dispute)
        resolved = dispute.model_copy(
            update={
                "status": "resolved",
                "resolved_at": resolved_at,
            }
        )
        self._disputes[dispute_id] = resolved
        self._append_event(
            {
                "action": "resolved",
                "dispute_id": dispute_id,
                "initiator_id": dispute.initiator_id,
                "respondent_id": dispute.respondent_id,
                "dispute_type": dispute.dispute_type,
                "judgement": dispute.judgement,
                "outcome": outcome,
                "consequences": consequences,
                "wall_time": resolved_at.isoformat(),
            }
        )
        return resolved, consequences

    def declare_war(
        self,
        *,
        initiator_id: str,
        target_faction_id: str,
        casus_belli: str,
        motivation: str | None = None,
    ) -> WarIntent | ConflictFailure:
        if self._diplomacy_ledger is None:
            return ConflictFailure(
                reason="agent_not_in_faction",
                detail="no diplomacy ledger configured",
            )
        initiator_faction = self._diplomacy_ledger.get_faction_for(initiator_id)
        if initiator_faction is None:
            return ConflictFailure(
                reason="agent_not_in_faction",
                detail=f"{initiator_id!r} is not a member of any faction",
            )
        if initiator_faction.faction_id == target_faction_id:
            return ConflictFailure(
                reason="self_dispute",
                detail="cannot declare war on own faction",
            )
        if self._diplomacy_ledger.get_faction(target_faction_id) is None:
            return ConflictFailure(
                reason="agent_not_in_faction",
                detail=f"target faction {target_faction_id!r} not registered",
            )
        member_count = len(initiator_faction.members)
        required_quorum = max(1, (member_count // 2) + 1)
        war = WarIntent(
            war_id=str(uuid.uuid4()),
            initiator_id=initiator_id,
            initiator_faction_id=initiator_faction.faction_id,
            target_faction_id=target_faction_id,
            casus_belli=casus_belli.strip() if isinstance(casus_belli, str) else "",
            motivation=(
                motivation.strip() if isinstance(motivation, str) and motivation.strip() else None
            ),
            seconders={initiator_id},
            required_quorum=required_quorum,
            status="pending",
            created_at=datetime.now(UTC),
        )
        if len(war.seconders) >= required_quorum:
            war = war.model_copy(update={"status": "active", "activated_at": war.created_at})
        self._wars[war.war_id] = war
        self._append_event(
            {
                "action": "war_declared",
                "war_id": war.war_id,
                "initiator_id": war.initiator_id,
                "initiator_faction_id": war.initiator_faction_id,
                "target_faction_id": war.target_faction_id,
                "casus_belli": war.casus_belli,
                "motivation": war.motivation,
                "seconders": sorted(war.seconders),
                "required_quorum": war.required_quorum,
                "status": war.status,
                "wall_time": war.created_at.isoformat(),
            }
        )
        if war.status == "active":
            self._append_event(
                {
                    "action": "war_activated",
                    "war_id": war.war_id,
                    "initiator_faction_id": war.initiator_faction_id,
                    "target_faction_id": war.target_faction_id,
                    "wall_time": war.created_at.isoformat(),
                }
            )
        return war

    def second_war(
        self,
        war_id: str,
        *,
        seconder_id: str,
    ) -> WarIntent | ConflictFailure:
        war = self._wars.get(war_id)
        if war is None:
            return ConflictFailure(reason="unknown_war", war_id=war_id)
        if war.status != "pending":
            return ConflictFailure(
                reason="not_active",
                war_id=war_id,
                detail=f"status={war.status}",
            )
        if self._diplomacy_ledger is not None:
            seconder_faction = self._diplomacy_ledger.get_faction_for(seconder_id)
            if seconder_faction is None or seconder_faction.faction_id != war.initiator_faction_id:
                return ConflictFailure(
                    reason="not_a_party",
                    war_id=war_id,
                    detail=(f"{seconder_id!r} is not a member of {war.initiator_faction_id!r}"),
                )
        new_seconders = set(war.seconders)
        new_seconders.add(seconder_id)
        when = datetime.now(UTC)
        updated = war.model_copy(update={"seconders": new_seconders})
        self._append_event(
            {
                "action": "war_seconded",
                "war_id": war_id,
                "seconder_id": seconder_id,
                "seconders": sorted(new_seconders),
                "required_quorum": war.required_quorum,
                "wall_time": when.isoformat(),
            }
        )
        if len(new_seconders) >= war.required_quorum:
            updated = updated.model_copy(update={"status": "active", "activated_at": when})
            self._append_event(
                {
                    "action": "war_activated",
                    "war_id": war_id,
                    "initiator_faction_id": war.initiator_faction_id,
                    "target_faction_id": war.target_faction_id,
                    "wall_time": when.isoformat(),
                }
            )
        self._wars[war_id] = updated
        return updated

    def surrender(
        self,
        target_id: str,
        *,
        surrendering_agent_id: str,
        terms: dict[str, Any] | None = None,
    ) -> WarIntent | Dispute | ConflictFailure:
        """End a war or dispute with surrender terms.

        ``target_id`` may be either a war_id or a dispute_id.
        """
        war = self._wars.get(target_id)
        if war is not None:
            if war.status != "active":
                return ConflictFailure(
                    reason="not_active",
                    war_id=target_id,
                    detail=f"status={war.status}",
                )
            resolved_at = datetime.now(UTC)
            updated_war = war.model_copy(
                update={
                    "status": "resolved",
                    "resolved_at": resolved_at,
                    "surrender_terms": dict(terms or {}),
                }
            )
            self._wars[target_id] = updated_war
            self._append_event(
                {
                    "action": "surrendered",
                    "war_id": target_id,
                    "surrendering_agent_id": surrendering_agent_id,
                    "terms": dict(terms or {}),
                    "wall_time": resolved_at.isoformat(),
                }
            )
            return updated_war

        dispute = self._disputes.get(target_id)
        if dispute is None:
            return ConflictFailure(
                reason="unknown_dispute",
                dispute_id=target_id,
                detail="no dispute or war with that id",
            )
        if dispute.status not in ("open", "judged"):
            return ConflictFailure(
                reason="not_open",
                dispute_id=target_id,
                detail=f"status={dispute.status}",
            )
        resolved_at = datetime.now(UTC)
        outcome = dict(dispute.outcome or {})
        outcome["surrendered_by"] = surrendering_agent_id
        outcome["terms"] = dict(terms or {})
        updated_dispute = dispute.model_copy(
            update={
                "status": "resolved",
                "outcome": outcome,
                "resolved_at": resolved_at,
            }
        )
        self._disputes[target_id] = updated_dispute
        self._append_event(
            {
                "action": "surrendered",
                "dispute_id": target_id,
                "initiator_id": dispute.initiator_id,
                "respondent_id": dispute.respondent_id,
                "dispute_type": dispute.dispute_type,
                "surrendering_agent_id": surrendering_agent_id,
                "terms": dict(terms or {}),
                "wall_time": resolved_at.isoformat(),
            }
        )
        return updated_dispute

    def advance_war_turn(self) -> list[dict[str, Any]]:
        """Return a per-turn relationship-delta payload for each active war.

        The caller mirrors these into the decision log; the ledger does
        not call the decision logger directly so it stays I/O-light.
        """
        deltas: list[dict[str, Any]] = []
        if self._diplomacy_ledger is None:
            return deltas
        for war in self.active_wars():
            initiator = self._diplomacy_ledger.get_faction(war.initiator_faction_id)
            target = self._diplomacy_ledger.get_faction(war.target_faction_id)
            if initiator is None or target is None:
                continue
            for src in sorted(initiator.members):
                for dst in sorted(target.members):
                    deltas.append(
                        {
                            "war_id": war.war_id,
                            "a": src,
                            "b": dst,
                            "before": {"trust": _DEFAULT_TRUST},
                            "after": {"trust": _DEFAULT_TRUST - _WAR_TICK_TRUST_HIT},
                            "reason": "war_ongoing",
                        }
                    )
        return deltas

    # ─── Internal helpers ──────────────────────────────────────────────

    def _auto_judge(self, dispute: Dispute) -> tuple[str, str]:
        """Score evidence + apply deterministic tiebreak → return (winner_id, judgement)."""
        initiator_score = 0.0
        respondent_score = 0.0
        support_index = self._build_support_index()
        for entry in dispute.evidence:
            weight = 2.0 if _ref_supported(entry, support_index=support_index) else 0.5
            submitter = entry.submitter_id
            if submitter == dispute.initiator_id:
                initiator_score += weight
            elif submitter == dispute.respondent_id:
                respondent_score += weight
            else:
                # Third-party evidence splits evenly so unattributed claims
                # don't tilt the ruling.
                initiator_score += weight / 2
                respondent_score += weight / 2
        if initiator_score > respondent_score:
            winner = dispute.initiator_id
        elif respondent_score > initiator_score:
            winner = dispute.respondent_id
        else:
            # Deterministic tiebreak from the simulation seed + dispute id.
            roll = _deterministic_score(self._simulation_id, dispute.dispute_id, "tiebreak")
            winner = dispute.initiator_id if roll < 0.5 else dispute.respondent_id
        judgement = (
            f"{winner} prevails: evidence weight {initiator_score:.1f} vs {respondent_score:.1f}"
        )
        return winner, judgement

    def _build_support_index(self) -> dict[str, set[str]]:
        """Collect known ids from sibling ledgers so evidence can be cross-referenced."""
        index: dict[str, set[str]] = {
            "theft": set(),
            "trade": set(),
            "ownership": set(),
            "diplomacy": set(),
            "utterance": set(),
        }
        if self._theft_ledger is not None:
            for attempt in getattr(self._theft_ledger, "all_attempts", lambda: [])():
                index["theft"].add(attempt.attempt_id)
        if self._trade_ledger is not None:
            # The trade ledger doesn't expose all offers cleanly; the offers
            # dict is internal but accessed via .get(offer_id). We treat any
            # ref_id as supported when the ledger can resolve it.
            offers = getattr(self._trade_ledger, "_offers", {}) or {}
            for offer_id in offers:
                index["trade"].add(offer_id)
        if self._ownership_ledger is not None:
            for claim in getattr(self._ownership_ledger, "all_active", lambda: [])():
                index["ownership"].add(claim.claim_id)
            by_id = getattr(self._ownership_ledger, "_by_id", {}) or {}
            for claim_id in by_id:
                index["ownership"].add(claim_id)
        if self._diplomacy_ledger is not None:
            treaties = getattr(self._diplomacy_ledger, "_treaties", {}) or {}
            for treaty_id in treaties:
                index["diplomacy"].add(treaty_id)
        return index

    def _apply_consequences(self, dispute: Dispute) -> list[dict[str, Any]]:
        """Route the consequence per dispute_type → list of summary dicts."""
        outcome = dispute.outcome or {}
        winner_id = outcome.get("winner_id")
        loser_id = outcome.get("loser_id")
        if not winner_id or not loser_id:
            return []
        consequences: list[dict[str, Any]] = []

        if dispute.dispute_type == "territorial":
            consequences.extend(
                self._apply_territorial_transfer(dispute, winner_id=winner_id, loser_id=loser_id)
            )
        elif dispute.dispute_type == "theft":
            consequences.extend(
                self._apply_theft_restitution(dispute, winner_id=winner_id, loser_id=loser_id)
            )
        elif dispute.dispute_type == "treaty_violation":
            consequences.extend(
                self._apply_treaty_break(dispute, winner_id=winner_id, loser_id=loser_id)
            )
        elif dispute.dispute_type == "trade_breach":
            consequences.append(
                {
                    "kind": "relationship_delta",
                    "a": winner_id,
                    "b": loser_id,
                    "before": {"trust": _DEFAULT_TRUST},
                    "after": {"trust": _DEFAULT_TRUST - _THEFT_LOSER_TRUST_HIT},
                    "reason": "trade_breach_resolved",
                }
            )
        elif dispute.dispute_type == "personal":
            consequences.append(
                {
                    "kind": "relationship_delta",
                    "a": winner_id,
                    "b": loser_id,
                    "before": {"trust": _DEFAULT_TRUST},
                    "after": {"trust": _DEFAULT_TRUST - _PERSONAL_LOSER_TRUST_HIT},
                    "reason": "personal_dispute_resolved",
                }
            )
        return consequences

    def _apply_territorial_transfer(
        self,
        dispute: Dispute,
        *,
        winner_id: str,
        loser_id: str,
    ) -> list[dict[str, Any]]:
        if self._ownership_ledger is None:
            return []
        transfers: list[dict[str, Any]] = []
        for entry in dispute.evidence:
            if entry.ref_type != "ownership":
                continue
            by_id = getattr(self._ownership_ledger, "_by_id", {}) or {}
            claim = by_id.get(entry.ref_id)
            if claim is None or claim.released_at is not None:
                continue
            if claim.owner_agent_id != loser_id:
                continue
            try:
                released = self._ownership_ledger.release(
                    claim.claim_id,
                    reason=f"dispute_resolution:{dispute.dispute_id}",
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("ownership.release failed during conflict resolution")
                continue
            new_claim = self._ownership_ledger.claim(
                owner_agent_id=winner_id,
                target_type=claim.target_type,
                target_ref=claim.target_ref,
                motivation=f"dispute_resolution:{dispute.dispute_id}",
            )
            new_claim_id = getattr(new_claim, "claim_id", None)
            transfers.append(
                {
                    "kind": "ownership_transfer",
                    "released_claim_id": released.claim_id if released else None,
                    "new_claim_id": new_claim_id,
                    "from_agent": loser_id,
                    "to_agent": winner_id,
                    "target_type": claim.target_type,
                    "target_ref": claim.target_ref,
                }
            )
        if not transfers:
            transfers.append(
                {
                    "kind": "relationship_delta",
                    "a": winner_id,
                    "b": loser_id,
                    "before": {"trust": _DEFAULT_TRUST},
                    "after": {"trust": _DEFAULT_TRUST - _PERSONAL_LOSER_TRUST_HIT},
                    "reason": "territorial_dispute_resolved",
                }
            )
        return transfers

    def _apply_theft_restitution(
        self,
        dispute: Dispute,
        *,
        winner_id: str,
        loser_id: str,
    ) -> list[dict[str, Any]]:
        consequences: list[dict[str, Any]] = [
            {
                "kind": "relationship_delta",
                "a": winner_id,
                "b": loser_id,
                "before": {"trust": _DEFAULT_TRUST},
                "after": {"trust": _DEFAULT_TRUST - _THEFT_LOSER_TRUST_HIT},
                "reason": "theft_dispute_resolved",
            }
        ]
        if self._trade_ledger is None or self._theft_ledger is None:
            return consequences
        restitution_items: dict[str, int] = {}
        for entry in dispute.evidence:
            if entry.ref_type != "theft":
                continue
            attempt = self._theft_ledger.get(entry.ref_id)
            if attempt is None:
                continue
            if attempt.thief_id != loser_id:
                continue
            for mat, qty in attempt.items.items():
                restitution_items[mat] = restitution_items.get(mat, 0) + int(qty)
        if not restitution_items:
            return consequences
        try:
            offer = self._trade_ledger.propose(
                proposer_id=loser_id,
                recipient_id=winner_id,
                give=restitution_items,
                want={},
                motivation=f"restitution:{dispute.dispute_id}",
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("trade_ledger.propose failed during conflict restitution")
            return consequences
        offer_id = getattr(offer, "offer_id", None)
        if offer_id is not None:
            consequences.append(
                {
                    "kind": "restitution_offer",
                    "offer_id": offer_id,
                    "from_agent": loser_id,
                    "to_agent": winner_id,
                    "items": dict(restitution_items),
                }
            )
        return consequences

    def _apply_treaty_break(
        self,
        dispute: Dispute,
        *,
        winner_id: str,
        loser_id: str,
    ) -> list[dict[str, Any]]:
        consequences: list[dict[str, Any]] = []
        if self._diplomacy_ledger is None:
            consequences.append(
                {
                    "kind": "relationship_delta",
                    "a": winner_id,
                    "b": loser_id,
                    "before": {"trust": _DEFAULT_TRUST},
                    "after": {"trust": _DEFAULT_TRUST - _PERSONAL_LOSER_TRUST_HIT},
                    "reason": "treaty_violation_resolved",
                }
            )
            return consequences
        broken_any = False
        for entry in dispute.evidence:
            if entry.ref_type != "diplomacy":
                continue
            treaty = self._diplomacy_ledger.get_treaty(entry.ref_id)
            if treaty is None or treaty.status != "active":
                continue
            result = self._diplomacy_ledger.break_(
                treaty.treaty_id,
                breaker_id=loser_id,
                reason=f"conflict_judgement:{dispute.dispute_id}",
            )
            if hasattr(result, "treaty_id"):
                broken_any = True
                consequences.append(
                    {
                        "kind": "treaty_break",
                        "treaty_id": result.treaty_id,
                        "parties": list(result.parties),
                        "breaker_id": loser_id,
                        "reason": "treaty_violation_resolved",
                    }
                )
        if not broken_any:
            consequences.append(
                {
                    "kind": "relationship_delta",
                    "a": winner_id,
                    "b": loser_id,
                    "before": {"trust": _DEFAULT_TRUST},
                    "after": {"trust": _DEFAULT_TRUST - _PERSONAL_LOSER_TRUST_HIT},
                    "reason": "treaty_violation_resolved",
                }
            )
        return consequences

    def _append_event(self, record: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:  # pragma: no cover - logging must not break sim
            logger.exception("conflict_log: failed to append event")

    def _replay(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line_no, raw in enumerate(fh, start=1):
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning("conflict_log: skipping malformed line %d", line_no)
                        continue
                    self._apply_replay(record)
        except OSError:  # pragma: no cover
            logger.exception("conflict_log: failed to replay")

    def _apply_replay(self, record: dict[str, Any]) -> None:
        action = record.get("action")
        wall_time_raw = record.get("wall_time")
        try:
            when = (
                datetime.fromisoformat(wall_time_raw)
                if isinstance(wall_time_raw, str)
                else datetime.now(UTC)
            )
        except ValueError:
            when = datetime.now(UTC)

        if action == "opened":
            dispute_id = record.get("dispute_id")
            if not isinstance(dispute_id, str):
                return
            try:
                evidence_raw = record.get("evidence") or []
                evidence = [EvidenceRef(**e) for e in evidence_raw if isinstance(e, dict)]
                dispute = Dispute(
                    dispute_id=dispute_id,
                    initiator_id=str(record.get("initiator_id") or ""),
                    respondent_id=str(record.get("respondent_id") or ""),
                    dispute_type=record.get("dispute_type") or "personal",
                    evidence=evidence,
                    status="open",
                    motivation=record.get("motivation"),
                    created_at=when,
                )
            except (TypeError, ValueError):
                return
            self._disputes[dispute_id] = dispute
            return

        if action == "evidence_submitted":
            dispute_id = record.get("dispute_id")
            existing = self._disputes.get(dispute_id) if isinstance(dispute_id, str) else None
            if existing is None or existing.status != "open":
                return
            entry_raw = record.get("evidence_entry")
            if not isinstance(entry_raw, dict):
                return
            try:
                entry = EvidenceRef(**entry_raw)
            except (TypeError, ValueError):
                return
            self._disputes[dispute_id] = existing.model_copy(
                update={"evidence": [*existing.evidence, entry]}
            )
            return

        if action == "judged":
            dispute_id = record.get("dispute_id")
            existing = self._disputes.get(dispute_id) if isinstance(dispute_id, str) else None
            if existing is None or existing.status != "open":
                return
            self._disputes[dispute_id] = existing.model_copy(
                update={
                    "status": "judged",
                    "judgement": record.get("judgement"),
                    "outcome": dict(record.get("outcome") or {}),
                    "judged_at": when,
                }
            )
            return

        if action == "resolved":
            dispute_id = record.get("dispute_id")
            existing = self._disputes.get(dispute_id) if isinstance(dispute_id, str) else None
            if existing is None:
                return
            self._disputes[dispute_id] = existing.model_copy(
                update={
                    "status": "resolved",
                    "resolved_at": when,
                    "outcome": dict(record.get("outcome") or existing.outcome or {}),
                }
            )
            return

        if action == "escalated":
            dispute_id = record.get("dispute_id")
            existing = self._disputes.get(dispute_id) if isinstance(dispute_id, str) else None
            if existing is None or existing.status != "judged":
                return
            self._disputes[dispute_id] = existing.model_copy(
                update={
                    "status": "escalated",
                    "resolved_at": when,
                }
            )
            return

        if action == "war_declared":
            war_id = record.get("war_id")
            if not isinstance(war_id, str):
                return
            try:
                seconders = set(record.get("seconders") or [record.get("initiator_id")])
                war = WarIntent(
                    war_id=war_id,
                    initiator_id=str(record.get("initiator_id") or ""),
                    initiator_faction_id=str(record.get("initiator_faction_id") or ""),
                    target_faction_id=str(record.get("target_faction_id") or ""),
                    casus_belli=str(record.get("casus_belli") or ""),
                    motivation=record.get("motivation"),
                    seconders={s for s in seconders if isinstance(s, str)},
                    required_quorum=int(record.get("required_quorum") or 1),
                    status=record.get("status") or "pending",
                    created_at=when,
                )
            except (TypeError, ValueError):
                return
            self._wars[war_id] = war
            return

        if action == "war_seconded":
            war_id = record.get("war_id")
            existing = self._wars.get(war_id) if isinstance(war_id, str) else None
            if existing is None:
                return
            new_seconders = set(existing.seconders)
            seconder_id = record.get("seconder_id")
            if isinstance(seconder_id, str):
                new_seconders.add(seconder_id)
            self._wars[war_id] = existing.model_copy(update={"seconders": new_seconders})
            return

        if action == "war_activated":
            war_id = record.get("war_id")
            existing = self._wars.get(war_id) if isinstance(war_id, str) else None
            if existing is None:
                return
            self._wars[war_id] = existing.model_copy(
                update={"status": "active", "activated_at": when}
            )
            return

        if action == "surrendered":
            war_id = record.get("war_id")
            dispute_id = record.get("dispute_id")
            terms = dict(record.get("terms") or {})
            if isinstance(war_id, str) and war_id in self._wars:
                self._wars[war_id] = self._wars[war_id].model_copy(
                    update={
                        "status": "resolved",
                        "resolved_at": when,
                        "surrender_terms": terms,
                    }
                )
                return
            if isinstance(dispute_id, str) and dispute_id in self._disputes:
                existing = self._disputes[dispute_id]
                outcome = dict(existing.outcome or {})
                outcome["surrendered_by"] = record.get("surrendering_agent_id")
                outcome["terms"] = terms
                self._disputes[dispute_id] = existing.model_copy(
                    update={
                        "status": "resolved",
                        "outcome": outcome,
                        "resolved_at": when,
                    }
                )


__all__ = [
    "ConflictAction",
    "ConflictFailure",
    "ConflictFailureReason",
    "ConflictLedger",
    "Dispute",
    "DisputeStatus",
    "DisputeType",
    "EvidenceRef",
    "WarIntent",
    "WarStatus",
]
