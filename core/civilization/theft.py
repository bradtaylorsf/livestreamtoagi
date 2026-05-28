"""Persistent theft ledger for the civilization MVP (issue #893).

Theft is the third civilization mechanic after ownership (#891) and trade
(#892). An agent attempts to take items from another agent's container; the
ledger rolls a *deterministic* detection check and, when detected, records
witnesses so consequence logic (relationship deltas) can fire.

Persistence is append-only JSONL at ``<sim_folder>/theft_log.jsonl``. On
construction the ledger replays the file (if present) so resumed sims
inherit prior attempts and any inventory mutations they caused.

The detection roll is intentionally seeded by ``simulation_id + tick +
thief_id`` so replays reproduce the same outcomes. Base detection is 50%,
each witness within ``witness_radius`` adds +10%, and a victim who is
"online" (e.g. participating in the conversation when the steal occurs)
adds +20%.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.civilization.ownership import OwnershipLedger
from core.civilization.trade import TradeLedger

logger = logging.getLogger(__name__)

_THEFT_LOG_FILENAME = "theft_log.jsonl"

TheftFailureReason = Literal[
    "self_theft",
    "empty_target",
    "trade_ledger_unavailable",
    "unknown_attempt",
]


def _normalize_container_ref(ref: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise ValueError("container_ref must be an object with x, y, z")
    try:
        x = int(ref["x"])
        y = int(ref["y"])
        z = int(ref["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("container_ref requires integer x, y, z keys") from exc
    dim = ref.get("dim")
    return {
        "x": x,
        "y": y,
        "z": z,
        "dim": str(dim) if dim is not None else "overworld",
    }


def _normalize_items(items: dict[str, Any] | None) -> dict[str, int]:
    if items is None:
        return {}
    if not isinstance(items, dict):
        raise ValueError("items must be a dict of material → quantity")
    out: dict[str, int] = {}
    for material, qty in items.items():
        if not isinstance(material, str) or not material:
            raise ValueError("items keys must be non-empty material strings")
        try:
            qty_int = int(qty)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"items quantity for {material!r} must be an integer") from exc
        if qty_int <= 0:
            continue
        out[material] = qty_int
    return out


class TheftAttempt(BaseModel):
    """A single theft attempt — outcome captured at roll time."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    thief_id: str
    victim_id: str
    target_container: dict[str, Any]
    items: dict[str, int] = Field(default_factory=dict)
    detected: bool
    witnesses: list[str] = Field(default_factory=list)
    motivation: str | None = None
    created_at: datetime


@dataclass(frozen=True)
class TheftFailure:
    """Returned when the attempt can't proceed at all."""

    status: Literal["error"] = "error"
    reason: TheftFailureReason = "unknown_attempt"
    detail: str | None = None


class TheftLedger:
    """In-memory theft index + append-only JSONL persistence.

    The ledger shares the :class:`TradeLedger` inventory model — a successful
    steal debits the *victim's* inventory (where the container's loot lives)
    and credits the thief's. This keeps the trade/theft mechanics consistent
    so a stolen stack acts identically to a freely-given one for downstream
    code (smoke reports, replay, eval scoring).

    Witness positions are read lazily through ``agent_positions``: a callable
    returning ``{agent_id: (x, y, z, dim)}``. The smoke wires the live
    proximity manager, tests supply a static fixture.
    """

    def __init__(
        self,
        sim_folder: str | Path | None,
        *,
        trade_ledger: TradeLedger,
        ownership_ledger: OwnershipLedger | None = None,
        simulation_id: str | uuid.UUID | None = None,
        witness_radius: int = 16,
        agent_positions: Callable[[], dict[str, tuple[int, int, int, str]]] | None = None,
    ) -> None:
        self._sim_folder: Path | None = Path(sim_folder) if sim_folder is not None else None
        self._path: Path | None = None
        if self._sim_folder is not None:
            self._sim_folder.mkdir(parents=True, exist_ok=True)
            self._path = self._sim_folder / _THEFT_LOG_FILENAME

        self._trade_ledger = trade_ledger
        self._ownership_ledger = ownership_ledger
        self._simulation_id = str(simulation_id) if simulation_id is not None else ""
        self._witness_radius = int(witness_radius)
        self._agent_positions = agent_positions

        # attempt_id → TheftAttempt
        self._attempts: dict[str, TheftAttempt] = {}

        self._replay()

    # ─── Public API ────────────────────────────────────────────────────

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def witness_radius(self) -> int:
        return self._witness_radius

    def all_attempts(self) -> list[TheftAttempt]:
        return list(self._attempts.values())

    def get(self, attempt_id: str) -> TheftAttempt | None:
        return self._attempts.get(attempt_id)

    def detection_roll(
        self,
        *,
        thief_id: str,
        tick: int,
        witness_count: int,
        victim_online: bool,
    ) -> tuple[bool, float, float]:
        """Deterministic detection roll. Returns (detected, roll, threshold)."""
        roll = _deterministic_roll(self._simulation_id, tick, thief_id)
        threshold = 0.5 + 0.10 * witness_count + (0.20 if victim_online else 0.0)
        return roll < threshold, roll, threshold

    def attempt(
        self,
        *,
        thief_id: str,
        victim_id: str,
        container_ref: dict[str, Any],
        items: dict[str, Any] | None,
        motivation: str | None,
        tick: int,
        victim_online: bool = False,
    ) -> TheftAttempt | TheftFailure:
        """Roll detection + atomically transfer (capped to available)."""
        if thief_id == victim_id:
            return TheftFailure(reason="self_theft", detail="cannot steal from self")
        try:
            container = _normalize_container_ref(container_ref)
            requested = _normalize_items(items)
        except ValueError as exc:
            return TheftFailure(reason="empty_target", detail=str(exc))

        # Cap requested → available in the victim's inventory.
        victim_inv = self._trade_ledger.get_inventory(victim_id)
        actual: dict[str, int] = {}
        for mat, qty in requested.items():
            available = int(victim_inv.get(mat, 0))
            take = min(qty, available)
            if take > 0:
                actual[mat] = take

        witnesses = self._compute_witnesses(
            thief_id=thief_id,
            victim_id=victim_id,
            container=container,
        )
        detected, roll, threshold = self.detection_roll(
            thief_id=thief_id,
            tick=tick,
            witness_count=len(witnesses),
            victim_online=victim_online,
        )

        # Atomically move items if any — but only when the steal actually
        # has something to take. An empty-target attempt is logged as a
        # no-op (still records the attempt, never transfers).
        if actual:
            for mat, qty in actual.items():
                self._trade_ledger.set_inventory(victim_id, mat, int(victim_inv.get(mat, 0)) - qty)
                thief_holdings = self._trade_ledger.get_inventory(thief_id)
                self._trade_ledger.set_inventory(
                    thief_id, mat, int(thief_holdings.get(mat, 0)) + qty
                )

        attempt = TheftAttempt(
            attempt_id=str(uuid.uuid4()),
            thief_id=thief_id,
            victim_id=victim_id,
            target_container=container,
            items=actual,
            detected=detected,
            witnesses=list(witnesses),
            motivation=motivation.strip() if isinstance(motivation, str) else None,
            created_at=datetime.now(UTC),
        )
        self._attempts[attempt.attempt_id] = attempt
        self._append_event(
            {
                "action": "attempt",
                "attempt_id": attempt.attempt_id,
                "thief_id": attempt.thief_id,
                "victim_id": attempt.victim_id,
                "target_container": attempt.target_container,
                "items": attempt.items,
                "detected": attempt.detected,
                "witnesses": attempt.witnesses,
                "motivation": attempt.motivation,
                "roll": roll,
                "threshold": threshold,
                "tick": tick,
                "victim_online": victim_online,
                "wall_time": attempt.created_at.isoformat(),
            }
        )
        return attempt

    def report_theft(
        self,
        *,
        witness_id: str,
        thief_id: str,
        container_ref: dict[str, Any],
    ) -> TheftAttempt | TheftFailure:
        """Promote the most recent matching undetected attempt to detected.

        Returns the (now-detected) attempt, or :class:`TheftFailure` when no
        matching attempt exists.
        """
        try:
            container = _normalize_container_ref(container_ref)
        except ValueError as exc:
            return TheftFailure(reason="empty_target", detail=str(exc))

        matches = [
            a
            for a in self._attempts.values()
            if a.thief_id == thief_id and a.target_container == container
        ]
        if not matches:
            return TheftFailure(
                reason="unknown_attempt",
                detail="no matching theft attempt found",
            )
        # Most recent first.
        matches.sort(key=lambda a: a.created_at, reverse=True)
        target = matches[0]

        updated_witnesses = list(target.witnesses)
        if witness_id not in updated_witnesses and witness_id != target.thief_id:
            updated_witnesses.append(witness_id)
        updated = target.model_copy(update={"detected": True, "witnesses": updated_witnesses})
        self._attempts[target.attempt_id] = updated
        self._append_event(
            {
                "action": "report",
                "attempt_id": target.attempt_id,
                "thief_id": target.thief_id,
                "victim_id": target.victim_id,
                "target_container": target.target_container,
                "items": target.items,
                "detected": True,
                "witnesses": updated_witnesses,
                "motivation": target.motivation,
                "witness_id": witness_id,
                "wall_time": datetime.now(UTC).isoformat(),
            }
        )
        return updated

    # ─── Internal helpers ──────────────────────────────────────────────

    def _compute_witnesses(
        self,
        *,
        thief_id: str,
        victim_id: str,
        container: dict[str, Any],
    ) -> list[str]:
        if self._agent_positions is None:
            return []
        try:
            positions = self._agent_positions()
        except Exception:  # pragma: no cover - defensive
            logger.exception("theft_log: agent_positions lookup failed")
            return []
        cx, cy, cz = container["x"], container["y"], container["z"]
        cdim = container.get("dim", "overworld")
        radius = self._witness_radius
        witnesses: list[str] = []
        for agent_id, pos in positions.items():
            if agent_id in (thief_id, victim_id):
                continue
            try:
                ax, ay, az, adim = pos
            except (TypeError, ValueError):
                continue
            if str(adim) != str(cdim):
                continue
            if (
                abs(int(ax) - cx) <= radius
                and abs(int(ay) - cy) <= radius
                and abs(int(az) - cz) <= radius
            ):
                witnesses.append(agent_id)
        return witnesses

    def _append_event(self, record: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:  # pragma: no cover - logging must not break sim
            logger.exception("theft_log: failed to append event")

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
                        logger.warning("theft_log: skipping malformed line %d", line_no)
                        continue
                    self._apply_replay(record)
        except OSError:  # pragma: no cover
            logger.exception("theft_log: failed to replay")

    def _apply_replay(self, record: dict[str, Any]) -> None:
        action = record.get("action")
        attempt_id = record.get("attempt_id")
        if not isinstance(attempt_id, str):
            return

        if action == "attempt":
            try:
                created_at_raw = record.get("wall_time")
                created_at = (
                    datetime.fromisoformat(created_at_raw)
                    if isinstance(created_at_raw, str)
                    else datetime.now(UTC)
                )
                container = record.get("target_container") or {}
                items = {k: int(v) for k, v in (record.get("items") or {}).items()}
                attempt = TheftAttempt(
                    attempt_id=attempt_id,
                    thief_id=record["thief_id"],
                    victim_id=record["victim_id"],
                    target_container=container,
                    items=items,
                    detected=bool(record.get("detected")),
                    witnesses=list(record.get("witnesses") or []),
                    motivation=record.get("motivation"),
                    created_at=created_at,
                )
            except (KeyError, ValueError, TypeError):
                return
            self._attempts[attempt_id] = attempt
            return

        if action == "report":
            existing = self._attempts.get(attempt_id)
            if existing is None:
                return
            self._attempts[attempt_id] = existing.model_copy(
                update={
                    "detected": True,
                    "witnesses": list(record.get("witnesses") or existing.witnesses),
                }
            )


def _deterministic_roll(simulation_id: str, tick: int, thief_id: str) -> float:
    """Hash (simulation_id, tick, thief_id) → float in [0, 1)."""
    blob = f"{simulation_id}|{tick}|{thief_id}".encode()
    digest = hashlib.sha256(blob).digest()
    # Use the first 8 bytes as an unsigned int and normalize to [0,1).
    n = int.from_bytes(digest[:8], "big")
    return n / (1 << 64)


__all__ = [
    "TheftAttempt",
    "TheftFailure",
    "TheftFailureReason",
    "TheftLedger",
]
