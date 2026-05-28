"""Persistent diplomacy ledger for the civilization MVP (issue #894).

Diplomacy is the fourth civilization mechanic after ownership (#891), trade
(#892), and theft (#893). It turns factions — already declared by scenario
YAML — into a real social fabric: agents can propose, sign, and break
treaties between factions, and individuals can defect from one faction to
another.

A treaty has a parties list (faction_ids) and a free-form ``terms`` dict
keyed on well-known intents:

* ``non_aggression`` — theft/conflict between treaty parties auto-applies a
  trust penalty *and* marks the treaty broken.
* ``trade_preference`` — the headless scorer weights intra-treaty trades
  higher.
* ``mutual_defense`` — when one party is theft-targeted, allies in the
  treaty get a defense goal injected.

Persistence is append-only JSONL at ``<sim_folder>/diplomacy_log.jsonl``.
The faction membership and treaty index replay on construction so resumed
sims inherit the diplomatic state.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_DIPLOMACY_LOG_FILENAME = "diplomacy_log.jsonl"

TreatyStatus = Literal["proposed", "active", "broken"]
DiplomacyAction = Literal["proposed", "signed", "broken", "defected"]
DiplomacyFailureReason = Literal[
    "unknown_treaty",
    "unknown_faction",
    "self_treaty",
    "duplicate_party",
    "not_a_party",
    "already_signed",
    "not_proposed",
    "not_active",
    "agent_not_in_faction",
    "invalid_terms",
]

_VALID_TERMS = frozenset({"non_aggression", "trade_preference", "mutual_defense"})


class Faction(BaseModel):
    """A named grouping of agents with treaties + enemies (issue #894)."""

    model_config = ConfigDict(extra="forbid")

    faction_id: str
    name: str
    members: set[str] = Field(default_factory=set)
    goal: str = ""
    stance: str | None = None
    treaties: list[str] = Field(default_factory=list)
    enemies: set[str] = Field(default_factory=set)


class Treaty(BaseModel):
    """A pairwise (or multi-party) treaty between factions."""

    model_config = ConfigDict(extra="forbid")

    treaty_id: str
    parties: list[str]
    terms: dict[str, Any] = Field(default_factory=dict)
    status: TreatyStatus = "proposed"
    proposer_id: str
    proposer_faction_id: str
    motivation: str | None = None
    created_at: datetime
    signed_at: datetime | None = None
    broken_at: datetime | None = None
    breaker_id: str | None = None
    break_reason: str | None = None


@dataclass(frozen=True)
class DiplomacyFailure:
    """Returned when a diplomacy action cannot proceed."""

    status: Literal["error"] = "error"
    reason: DiplomacyFailureReason = "unknown_treaty"
    treaty_id: str | None = None
    detail: str | None = None


def _slugify(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "faction"


def _normalize_terms(terms: dict[str, Any] | None) -> dict[str, Any]:
    if terms is None:
        return {}
    if not isinstance(terms, dict):
        raise ValueError("terms must be an object")
    out: dict[str, Any] = {}
    for key, value in terms.items():
        if not isinstance(key, str) or key not in _VALID_TERMS:
            raise ValueError(f"unknown treaty term {key!r}; allowed: {sorted(_VALID_TERMS)}")
        out[key] = bool(value) if isinstance(value, bool) else value
    return out


class DiplomacyLedger:
    """In-memory faction + treaty index with append-only JSONL persistence."""

    def __init__(
        self,
        sim_folder: str | Path | None,
        *,
        simulation_id: str | uuid.UUID | None = None,
        factions: Iterable[Any] | None = None,
    ) -> None:
        self._sim_folder: Path | None = Path(sim_folder) if sim_folder is not None else None
        self._path: Path | None = None
        if self._sim_folder is not None:
            self._sim_folder.mkdir(parents=True, exist_ok=True)
            self._path = self._sim_folder / _DIPLOMACY_LOG_FILENAME

        self._simulation_id = str(simulation_id) if simulation_id is not None else ""
        self._factions: dict[str, Faction] = {}
        self._treaties: dict[str, Treaty] = {}

        if factions is not None:
            for fc in factions:
                self._seed_faction(fc)

        self._replay()

    # ─── Public properties ─────────────────────────────────────────────

    @property
    def path(self) -> Path | None:
        return self._path

    def factions(self) -> list[Faction]:
        return list(self._factions.values())

    def get_faction(self, faction_id: str) -> Faction | None:
        return self._factions.get(faction_id)

    def get_faction_for(self, agent_id: str) -> Faction | None:
        for faction in self._factions.values():
            if agent_id in faction.members:
                return faction
        return None

    def get_treaty(self, treaty_id: str) -> Treaty | None:
        return self._treaties.get(treaty_id)

    def list_active_treaties(self, faction_id: str | None = None) -> list[Treaty]:
        active = [t for t in self._treaties.values() if t.status == "active"]
        if faction_id is None:
            return active
        return [t for t in active if faction_id in t.parties]

    def treaties_between(self, faction_a: str, faction_b: str) -> list[Treaty]:
        return [
            t
            for t in self._treaties.values()
            if t.status == "active" and faction_a in t.parties and faction_b in t.parties
        ]

    def has_non_aggression(self, faction_a: str, faction_b: str) -> bool:
        if faction_a == faction_b:
            return False
        for treaty in self.treaties_between(faction_a, faction_b):
            if treaty.terms.get("non_aggression"):
                return True
        return False

    def has_mutual_defense(self, faction_a: str, faction_b: str) -> bool:
        if faction_a == faction_b:
            return False
        for treaty in self.treaties_between(faction_a, faction_b):
            if treaty.terms.get("mutual_defense"):
                return True
        return False

    def mutual_defenders_of(self, faction_id: str) -> list[str]:
        """Return agent_ids in any faction with an active mutual_defense treaty.

        Excludes members of ``faction_id`` itself — the caller is the
        victim's faction; allies are *other* factions sworn to defend it.
        """
        defenders: list[str] = []
        for treaty in self.list_active_treaties(faction_id):
            if not treaty.terms.get("mutual_defense"):
                continue
            for party in treaty.parties:
                if party == faction_id:
                    continue
                ally = self._factions.get(party)
                if ally is not None:
                    defenders.extend(sorted(ally.members))
        return defenders

    # ─── Mutating API ──────────────────────────────────────────────────

    def propose(
        self,
        *,
        proposer_id: str,
        proposer_faction_id: str,
        other_faction_id: str,
        terms: dict[str, Any] | None,
        motivation: str | None = None,
    ) -> Treaty | DiplomacyFailure:
        if proposer_faction_id == other_faction_id:
            return DiplomacyFailure(
                reason="self_treaty",
                detail="cannot treaty with own faction",
            )
        if proposer_faction_id not in self._factions:
            return DiplomacyFailure(
                reason="unknown_faction",
                detail=f"proposer faction {proposer_faction_id!r} not registered",
            )
        if other_faction_id not in self._factions:
            return DiplomacyFailure(
                reason="unknown_faction",
                detail=f"other faction {other_faction_id!r} not registered",
            )
        if proposer_id not in self._factions[proposer_faction_id].members:
            return DiplomacyFailure(
                reason="agent_not_in_faction",
                detail=(f"{proposer_id!r} is not a member of {proposer_faction_id!r}"),
            )
        try:
            terms_norm = _normalize_terms(terms)
        except ValueError as exc:
            return DiplomacyFailure(reason="invalid_terms", detail=str(exc))

        treaty = Treaty(
            treaty_id=str(uuid.uuid4()),
            parties=[proposer_faction_id, other_faction_id],
            terms=terms_norm,
            status="proposed",
            proposer_id=proposer_id,
            proposer_faction_id=proposer_faction_id,
            motivation=motivation.strip() if isinstance(motivation, str) else None,
            created_at=datetime.now(UTC),
        )
        self._treaties[treaty.treaty_id] = treaty
        self._append_event(
            {
                "action": "proposed",
                "treaty_id": treaty.treaty_id,
                "parties": list(treaty.parties),
                "terms": dict(treaty.terms),
                "proposer_id": treaty.proposer_id,
                "proposer_faction_id": treaty.proposer_faction_id,
                "motivation": treaty.motivation,
                "wall_time": treaty.created_at.isoformat(),
            }
        )
        return treaty

    def sign(
        self,
        treaty_id: str,
        *,
        signer_id: str,
        signer_faction_id: str | None = None,
    ) -> Treaty | DiplomacyFailure:
        treaty = self._treaties.get(treaty_id)
        if treaty is None:
            return DiplomacyFailure(reason="unknown_treaty", treaty_id=treaty_id)
        if treaty.status == "active":
            return DiplomacyFailure(
                reason="already_signed",
                treaty_id=treaty_id,
                detail="treaty already active",
            )
        if treaty.status != "proposed":
            return DiplomacyFailure(
                reason="not_proposed",
                treaty_id=treaty_id,
                detail=f"status={treaty.status}",
            )

        if signer_faction_id is None:
            faction = self.get_faction_for(signer_id)
            if faction is None:
                return DiplomacyFailure(
                    reason="agent_not_in_faction",
                    treaty_id=treaty_id,
                    detail=f"{signer_id!r} is not in any faction",
                )
            signer_faction_id = faction.faction_id

        if signer_faction_id not in treaty.parties:
            return DiplomacyFailure(
                reason="not_a_party",
                treaty_id=treaty_id,
                detail=(f"faction {signer_faction_id!r} is not a party to this treaty"),
            )
        if signer_faction_id == treaty.proposer_faction_id:
            return DiplomacyFailure(
                reason="not_a_party",
                treaty_id=treaty_id,
                detail="proposer faction cannot also sign",
            )

        signed_at = datetime.now(UTC)
        signed = treaty.model_copy(update={"status": "active", "signed_at": signed_at})
        self._treaties[treaty_id] = signed
        for fid in signed.parties:
            faction = self._factions.get(fid)
            if faction is not None and treaty_id not in faction.treaties:
                faction.treaties.append(treaty_id)
        self._append_event(
            {
                "action": "signed",
                "treaty_id": treaty_id,
                "parties": list(signed.parties),
                "terms": dict(signed.terms),
                "signer_id": signer_id,
                "signer_faction_id": signer_faction_id,
                "wall_time": signed_at.isoformat(),
            }
        )
        return signed

    def break_(
        self,
        treaty_id: str,
        *,
        breaker_id: str,
        reason: str,
    ) -> Treaty | DiplomacyFailure:
        treaty = self._treaties.get(treaty_id)
        if treaty is None:
            return DiplomacyFailure(reason="unknown_treaty", treaty_id=treaty_id)
        if treaty.status != "active":
            return DiplomacyFailure(
                reason="not_active",
                treaty_id=treaty_id,
                detail=f"status={treaty.status}",
            )
        broken_at = datetime.now(UTC)
        broken = treaty.model_copy(
            update={
                "status": "broken",
                "broken_at": broken_at,
                "breaker_id": breaker_id,
                "break_reason": reason,
            }
        )
        self._treaties[treaty_id] = broken
        self._append_event(
            {
                "action": "broken",
                "treaty_id": treaty_id,
                "parties": list(broken.parties),
                "terms": dict(broken.terms),
                "breaker_id": breaker_id,
                "reason": reason,
                "wall_time": broken_at.isoformat(),
            }
        )
        return broken

    def defect(
        self,
        *,
        agent_id: str,
        target_faction_id: str,
        motivation: str | None = None,
    ) -> tuple[str | None, str] | DiplomacyFailure:
        """Move agent into target faction; returns (old_faction_id, new_faction_id)."""
        if target_faction_id not in self._factions:
            return DiplomacyFailure(
                reason="unknown_faction",
                detail=f"target faction {target_faction_id!r} not registered",
            )
        current = self.get_faction_for(agent_id)
        old_id = current.faction_id if current is not None else None
        if old_id == target_faction_id:
            return DiplomacyFailure(
                reason="self_treaty",
                detail="already a member of target faction",
            )
        if current is not None:
            current.members.discard(agent_id)
        self._factions[target_faction_id].members.add(agent_id)
        when = datetime.now(UTC)
        self._append_event(
            {
                "action": "defected",
                "treaty_id": None,
                "parties": [],
                "terms": {},
                "defector_id": agent_id,
                "from_faction": old_id,
                "to_faction": target_faction_id,
                "motivation": (motivation.strip() if isinstance(motivation, str) else None),
                "wall_time": when.isoformat(),
            }
        )
        return (old_id, target_faction_id)

    # ─── Internal helpers ──────────────────────────────────────────────

    def _seed_faction(self, fc: Any) -> None:
        name = getattr(fc, "name", None) or (fc.get("name") if isinstance(fc, dict) else None)
        members_iter = getattr(fc, "members", None) or (
            fc.get("members") if isinstance(fc, dict) else []
        )
        goal = getattr(fc, "goal", None) or (fc.get("goal") if isinstance(fc, dict) else "")
        stance = getattr(fc, "stance", None) or (fc.get("stance") if isinstance(fc, dict) else None)
        if not isinstance(name, str) or not name:
            return
        faction_id = _slugify(name)
        members = {str(m) for m in (members_iter or []) if isinstance(m, str) and m}
        existing = self._factions.get(faction_id)
        if existing is not None:
            existing.members.update(members)
            if not existing.goal:
                existing.goal = goal or ""
            if stance is not None:
                existing.stance = stance
            return
        self._factions[faction_id] = Faction(
            faction_id=faction_id,
            name=name,
            members=members,
            goal=goal or "",
            stance=stance,
        )

    def _append_event(self, record: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:  # pragma: no cover - logging must not break sim
            logger.exception("diplomacy_log: failed to append event")

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
                        logger.warning("diplomacy_log: skipping malformed line %d", line_no)
                        continue
                    self._apply_replay(record)
        except OSError:  # pragma: no cover
            logger.exception("diplomacy_log: failed to replay")

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

        if action == "proposed":
            treaty_id = record.get("treaty_id")
            if not isinstance(treaty_id, str):
                return
            try:
                treaty = Treaty(
                    treaty_id=treaty_id,
                    parties=list(record.get("parties") or []),
                    terms=dict(record.get("terms") or {}),
                    status="proposed",
                    proposer_id=str(record.get("proposer_id") or ""),
                    proposer_faction_id=str(record.get("proposer_faction_id") or ""),
                    motivation=record.get("motivation"),
                    created_at=when,
                )
            except (TypeError, ValueError):
                return
            self._treaties[treaty_id] = treaty
            return

        if action == "signed":
            treaty_id = record.get("treaty_id")
            existing = self._treaties.get(treaty_id) if isinstance(treaty_id, str) else None
            if existing is None or existing.status != "proposed":
                return
            self._treaties[treaty_id] = existing.model_copy(
                update={"status": "active", "signed_at": when}
            )
            for fid in existing.parties:
                faction = self._factions.get(fid)
                if faction is not None and treaty_id not in faction.treaties:
                    faction.treaties.append(treaty_id)
            return

        if action == "broken":
            treaty_id = record.get("treaty_id")
            existing = self._treaties.get(treaty_id) if isinstance(treaty_id, str) else None
            if existing is None or existing.status != "active":
                return
            self._treaties[treaty_id] = existing.model_copy(
                update={
                    "status": "broken",
                    "broken_at": when,
                    "breaker_id": record.get("breaker_id"),
                    "break_reason": record.get("reason"),
                }
            )
            return

        if action == "defected":
            defector_id = record.get("defector_id")
            to_faction = record.get("to_faction")
            if not isinstance(defector_id, str) or not isinstance(to_faction, str):
                return
            if to_faction not in self._factions:
                return
            from_faction = record.get("from_faction")
            if isinstance(from_faction, str):
                old = self._factions.get(from_faction)
                if old is not None:
                    old.members.discard(defector_id)
            self._factions[to_faction].members.add(defector_id)


__all__ = [
    "DiplomacyAction",
    "DiplomacyFailure",
    "DiplomacyFailureReason",
    "DiplomacyLedger",
    "Faction",
    "Treaty",
    "TreatyStatus",
]
