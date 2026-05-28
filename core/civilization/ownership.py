"""Persistent ownership ledger for the civilization MVP (issue #891).

Every other civilization mechanic (trade, theft, diplomacy, conflict) needs
to know *who owns what* before it can resolve a transaction or a dispute.

The ledger supports three target types:

* ``structure`` — by ``intent_id`` from an earlier ``propose_build`` call.
* ``container`` — chests at specific block coordinates ``{x, y, z, dim}``.
* ``region`` — axis-aligned bounding-box claims
  ``{x1, z1, x2, z2, dim?}`` (Y is intentionally ignored — region claims
  are over the surface footprint, not the vertical column).

Conflict resolution is first-claim-wins: any subsequent claim against an
already-owned target (or, for regions, any overlapping bbox) returns an
:class:`OwnershipConflict` rather than mutating the index.

Persistence is append-only JSONL at ``<sim_folder>/ownership_log.jsonl``.
On construction the ledger replays the file (if present) so resumed sims
inherit prior claims without bespoke migration code.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

_OWNERSHIP_LOG_FILENAME = "ownership_log.jsonl"

TargetType = Literal["region", "structure", "container"]
OwnershipAction = Literal["claim", "release", "conflict"]


class OwnershipClaim(BaseModel):
    """A single ownership claim — append-only once active."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    owner_agent_id: str
    target_type: TargetType
    target_ref: dict[str, Any]
    motivation: str
    created_at: datetime
    released_at: datetime | None = None
    release_reason: str | None = None


class OwnershipConflict(BaseModel):
    """Returned when a claim collides with an existing active claim."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["conflict"] = "conflict"
    target_type: TargetType
    target_ref: dict[str, Any]
    existing_claim_id: str
    existing_owner_agent_id: str


def normalize_region_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Coerce a region target_ref to a canonical {x1<=x2, z1<=z2} form."""
    try:
        x1 = int(ref["x1"])
        z1 = int(ref["z1"])
        x2 = int(ref["x2"])
        z2 = int(ref["z2"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "region target_ref requires integer x1, z1, x2, z2 keys"
        ) from exc
    lo_x, hi_x = min(x1, x2), max(x1, x2)
    lo_z, hi_z = min(z1, z2), max(z1, z2)
    out: dict[str, Any] = {"x1": lo_x, "z1": lo_z, "x2": hi_x, "z2": hi_z}
    dim = ref.get("dim")
    out["dim"] = str(dim) if dim is not None else "overworld"
    return out


def _region_dim(ref: dict[str, Any]) -> str:
    dim = ref.get("dim")
    return str(dim) if dim is not None else "overworld"


def _regions_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff two normalized region refs overlap (same dim + bbox intersect)."""
    if _region_dim(a) != _region_dim(b):
        return False
    if a["x2"] < b["x1"] or b["x2"] < a["x1"]:
        return False
    return not (a["z2"] < b["z1"] or b["z2"] < a["z1"])


def canonical_target_ref(target_type: TargetType, ref: dict[str, Any]) -> dict[str, Any]:
    """Normalize a target_ref so equality lookups are stable."""
    if target_type == "structure":
        intent_id = ref.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            raise ValueError("structure target_ref requires string 'intent_id'")
        return {"intent_id": intent_id}
    if target_type == "container":
        try:
            x = int(ref["x"])
            y = int(ref["y"])
            z = int(ref["z"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "container target_ref requires integer x, y, z keys"
            ) from exc
        dim = ref.get("dim")
        return {
            "x": x,
            "y": y,
            "z": z,
            "dim": str(dim) if dim is not None else "overworld",
        }
    if target_type == "region":
        return normalize_region_ref(ref)
    raise ValueError(f"unknown target_type: {target_type!r}")


def _ref_key(target_type: TargetType, ref: dict[str, Any]) -> str:
    """Hashable key for exact-match (non-region) lookups."""
    if target_type == "structure":
        return f"structure::{ref['intent_id']}"
    if target_type == "container":
        return f"container::{ref['dim']}::{ref['x']},{ref['y']},{ref['z']}"
    # Region falls back to canonical bbox-as-string but lookups use overlap.
    return (
        f"region::{ref['dim']}::"
        f"{ref['x1']},{ref['z1']}::{ref['x2']},{ref['z2']}"
    )


class OwnershipLedger:
    """In-memory ownership index + append-only JSONL persistence.

    Re-instantiating the ledger against an existing sim folder replays
    ``ownership_log.jsonl`` to rebuild the active index — supports resumed
    long-running sims (epic #820) without bespoke migration code.
    """

    def __init__(self, sim_folder: str | Path | None) -> None:
        self._sim_folder: Path | None = Path(sim_folder) if sim_folder is not None else None
        self._path: Path | None = None
        if self._sim_folder is not None:
            self._sim_folder.mkdir(parents=True, exist_ok=True)
            self._path = self._sim_folder / _OWNERSHIP_LOG_FILENAME

        # Active claims keyed by canonical ref string. Region claims are
        # ALSO tracked in this dict but lookups iterate for overlap.
        self._active: dict[str, OwnershipClaim] = {}
        # All claims by claim_id (including released) for release/get-by-id.
        self._by_id: dict[str, OwnershipClaim] = {}
        # All region claims (active only) for overlap checks.
        self._active_regions: list[OwnershipClaim] = []

        self._replay()

    # ─── Public API ────────────────────────────────────────────────────

    @property
    def path(self) -> Path | None:
        return self._path

    def claim(
        self,
        *,
        owner_agent_id: str,
        target_type: TargetType,
        target_ref: dict[str, Any],
        motivation: str,
    ) -> OwnershipClaim | OwnershipConflict:
        """Attempt to claim a target. First-claim-wins."""
        try:
            canonical = canonical_target_ref(target_type, target_ref)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        existing = self._find_conflict(target_type, canonical)
        if existing is not None:
            conflict = OwnershipConflict(
                target_type=target_type,
                target_ref=canonical,
                existing_claim_id=existing.claim_id,
                existing_owner_agent_id=existing.owner_agent_id,
            )
            self._append_event(
                action="conflict",
                claim_id=existing.claim_id,
                owner_agent_id=owner_agent_id,
                target_type=target_type,
                target_ref=canonical,
                motivation=motivation,
            )
            return conflict

        claim = OwnershipClaim(
            claim_id=str(uuid.uuid4()),
            owner_agent_id=owner_agent_id,
            target_type=target_type,
            target_ref=canonical,
            motivation=motivation,
            created_at=datetime.now(UTC),
        )
        self._index_active(claim)
        self._append_event(
            action="claim",
            claim_id=claim.claim_id,
            owner_agent_id=owner_agent_id,
            target_type=target_type,
            target_ref=canonical,
            motivation=motivation,
        )
        return claim

    def release(
        self,
        claim_id: str,
        *,
        reason: str | None = None,
    ) -> OwnershipClaim | None:
        """Release an active claim. Returns the updated claim or None."""
        claim = self._by_id.get(claim_id)
        if claim is None or claim.released_at is not None:
            return None
        released = claim.model_copy(
            update={
                "released_at": datetime.now(UTC),
                "release_reason": reason,
            }
        )
        self._by_id[claim_id] = released
        self._deindex_active(claim)
        self._append_event(
            action="release",
            claim_id=claim_id,
            owner_agent_id=released.owner_agent_id,
            target_type=released.target_type,
            target_ref=released.target_ref,
            motivation=reason or "",
        )
        return released

    def get(
        self,
        target_type: TargetType,
        target_ref: dict[str, Any],
    ) -> OwnershipClaim | None:
        """Return the active owner of a target, if any."""
        canonical = canonical_target_ref(target_type, target_ref)
        return self._find_conflict(target_type, canonical)

    def list_owned_by(self, agent_id: str) -> list[OwnershipClaim]:
        """Return all active claims held by an agent (creation order)."""
        return [
            c
            for c in self._active.values()
            if c.owner_agent_id == agent_id
        ]

    def all_active(self) -> list[OwnershipClaim]:
        return list(self._active.values())

    # ─── Internal helpers ──────────────────────────────────────────────

    def _find_conflict(
        self,
        target_type: TargetType,
        canonical_ref: dict[str, Any],
    ) -> OwnershipClaim | None:
        if target_type == "region":
            for r in self._active_regions:
                if _regions_overlap(canonical_ref, r.target_ref):
                    return r
            return None
        return self._active.get(_ref_key(target_type, canonical_ref))

    def _index_active(self, claim: OwnershipClaim) -> None:
        self._active[_ref_key(claim.target_type, claim.target_ref)] = claim
        self._by_id[claim.claim_id] = claim
        if claim.target_type == "region":
            self._active_regions.append(claim)

    def _deindex_active(self, claim: OwnershipClaim) -> None:
        self._active.pop(_ref_key(claim.target_type, claim.target_ref), None)
        if claim.target_type == "region":
            self._active_regions = [
                r for r in self._active_regions if r.claim_id != claim.claim_id
            ]

    def _append_event(
        self,
        *,
        action: OwnershipAction,
        claim_id: str,
        owner_agent_id: str,
        target_type: TargetType,
        target_ref: dict[str, Any],
        motivation: str,
    ) -> None:
        if self._path is None:
            return
        record = {
            "action": action,
            "claim_id": claim_id,
            "owner_agent_id": owner_agent_id,
            "target_type": target_type,
            "target_ref": target_ref,
            "motivation": motivation,
            "wall_time": datetime.now(UTC).isoformat(),
        }
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:  # pragma: no cover - logging must not break sim
            logger.exception("ownership_log: failed to append event")

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
                        logger.warning(
                            "ownership_log: skipping malformed line %d", line_no
                        )
                        continue
                    self._apply_replay(record)
        except OSError:  # pragma: no cover
            logger.exception("ownership_log: failed to replay")

    def _apply_replay(self, record: dict[str, Any]) -> None:
        action = record.get("action")
        claim_id = record.get("claim_id")
        if not isinstance(claim_id, str):
            return
        if action == "claim":
            try:
                target_type = record["target_type"]
                target_ref = record["target_ref"]
                owner_agent_id = record["owner_agent_id"]
                created_at_raw = record.get("wall_time")
                created_at = (
                    datetime.fromisoformat(created_at_raw)
                    if isinstance(created_at_raw, str)
                    else datetime.now(UTC)
                )
            except KeyError:
                return
            claim = OwnershipClaim(
                claim_id=claim_id,
                owner_agent_id=owner_agent_id,
                target_type=target_type,
                target_ref=target_ref,
                motivation=record.get("motivation", "") or "",
                created_at=created_at,
            )
            # Conflicts in the log don't index; only successful claims do.
            self._index_active(claim)
        elif action == "release":
            claim = self._by_id.get(claim_id)
            if claim is None or claim.released_at is not None:
                return
            released_at_raw = record.get("wall_time")
            released_at = (
                datetime.fromisoformat(released_at_raw)
                if isinstance(released_at_raw, str)
                else datetime.now(UTC)
            )
            updated = claim.model_copy(
                update={
                    "released_at": released_at,
                    "release_reason": record.get("motivation") or None,
                }
            )
            self._by_id[claim_id] = updated
            self._deindex_active(claim)
        # action == "conflict" — informational only, no state change.


__all__ = [
    "OwnershipAction",
    "OwnershipClaim",
    "OwnershipConflict",
    "OwnershipLedger",
    "TargetType",
    "canonical_target_ref",
    "normalize_region_ref",
]
