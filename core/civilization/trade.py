"""Persistent trade ledger for the civilization MVP (issue #892).

Trade is the second civilization mechanic after ownership (issue #891). It
moves materials (cobblestone, wood, food, …) between two agents' inventories
at a mutually agreed quantity. Agents *propose* a trade, the recipient
*accepts* or *rejects*, and the ledger atomically swaps items when both
sides have the inventory to back the offer.

Persistence is append-only JSONL at ``<sim_folder>/trade_log.jsonl``.
On construction the ledger replays the file (if present) so resumed sims
inherit prior offers, completed trades, and inventory balances without
bespoke migration code.

Container-owned items: when a ``give`` or ``want`` entry references a
container (``target_type='container'`` with ``target_ref={x, y, z, dim}``)
and the caller provides an :class:`~core.civilization.ownership.OwnershipLedger`,
the accepted trade also transfers ownership via release + claim. This keeps
the two MVP mechanics consistent so a chest gifted in a trade actually
changes hands in the ownership index.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_TRADE_LOG_FILENAME = "trade_log.jsonl"

TradeStatus = Literal["pending", "accepted", "rejected", "expired"]
TradeAction = Literal["proposed", "accepted", "rejected", "expired"]
TradeFailureReason = Literal[
    "unknown_offer",
    "already_resolved",
    "wrong_recipient",
    "insufficient_inventory",
    "self_trade",
    "empty_trade",
]


class TradeOffer(BaseModel):
    """A pairwise trade offer — pending until accepted, rejected, or expired.

    ``give_containers`` / ``want_containers`` are optional lists of container
    target_refs (``{x, y, z, dim}``) that change hands alongside the material
    bundles. When the recipient accepts and an
    :class:`~core.civilization.ownership.OwnershipLedger` is supplied, the
    ledger releases the prior claim and re-claims the container for the new
    owner so the ownership index stays consistent.
    """

    model_config = ConfigDict(extra="forbid")

    offer_id: str
    proposer_id: str
    recipient_id: str
    give: dict[str, int] = Field(default_factory=dict)
    want: dict[str, int] = Field(default_factory=dict)
    give_containers: list[dict[str, Any]] = Field(default_factory=list)
    want_containers: list[dict[str, Any]] = Field(default_factory=list)
    motivation: str | None = None
    status: TradeStatus = "pending"
    created_at: datetime
    resolved_at: datetime | None = None
    reject_reason: str | None = None


@dataclass(frozen=True)
class TradeFailure:
    """Returned by accept/reject when the action cannot proceed."""

    status: Literal["error"] = "error"
    reason: TradeFailureReason = "unknown_offer"
    offer_id: str | None = None
    detail: str | None = None


def _normalize_bundle(bundle: dict[str, Any] | None, *, label: str) -> dict[str, int]:
    """Validate and copy a give/want bundle into ``{material: int qty>0}``.

    Accepts an empty dict (so a trade can be containers-only); rejects any
    non-dict, non-int qty, or non-positive qty entry.
    """
    if bundle is None:
        return {}
    if not isinstance(bundle, dict):
        raise ValueError(f"{label} must be a dict of material → quantity")
    normalized: dict[str, int] = {}
    for material, qty in bundle.items():
        if not isinstance(material, str) or not material:
            raise ValueError(f"{label} keys must be non-empty strings (material names)")
        try:
            qty_int = int(qty)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} quantity for {material!r} must be an integer") from exc
        if qty_int <= 0:
            raise ValueError(f"{label} quantity for {material!r} must be positive (got {qty_int})")
        normalized[material] = qty_int
    return normalized


def _normalize_containers(
    containers: list[Any] | None,
    *,
    label: str,
) -> list[dict[str, Any]]:
    """Validate a list of container target_refs (``{x, y, z, dim?}``)."""
    if containers is None:
        return []
    if not isinstance(containers, list):
        raise ValueError(f"{label} must be a list of container target_refs")
    normalized: list[dict[str, Any]] = []
    for ref in containers:
        if not isinstance(ref, dict):
            raise ValueError(f"{label} entries must be objects")
        try:
            x = int(ref["x"])
            y = int(ref["y"])
            z = int(ref["z"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{label} entries require integer 'x', 'y', 'z' keys") from exc
        dim = ref.get("dim")
        normalized.append(
            {
                "x": x,
                "y": y,
                "z": z,
                "dim": str(dim) if dim is not None else "overworld",
            }
        )
    return normalized


def _has_inventory(
    inventory: dict[str, dict[str, int]],
    agent_id: str,
    bundle: dict[str, int],
) -> bool:
    holdings = inventory.get(agent_id, {})
    return all(holdings.get(mat, 0) >= qty for mat, qty in bundle.items())


def _apply_inventory_delta(
    inventory: dict[str, dict[str, int]],
    *,
    debit_agent: str,
    credit_agent: str,
    bundle: dict[str, int],
) -> None:
    debit = inventory.setdefault(debit_agent, {})
    credit = inventory.setdefault(credit_agent, {})
    for mat, qty in bundle.items():
        debit[mat] = debit.get(mat, 0) - qty
        if debit[mat] == 0:
            del debit[mat]
        credit[mat] = credit.get(mat, 0) + qty


class TradeLedger:
    """In-memory inventory + offer index with append-only JSONL persistence.

    Re-instantiating the ledger against an existing sim folder replays
    ``trade_log.jsonl`` to rebuild inventories and the pending-offers index —
    supports resumed long-running sims (epic #820).
    """

    def __init__(self, sim_folder: str | Path | None) -> None:
        self._sim_folder: Path | None = Path(sim_folder) if sim_folder is not None else None
        self._path: Path | None = None
        if self._sim_folder is not None:
            self._sim_folder.mkdir(parents=True, exist_ok=True)
            self._path = self._sim_folder / _TRADE_LOG_FILENAME

        # agent_id → {material: qty}
        self._inventory: dict[str, dict[str, int]] = {}
        # offer_id → TradeOffer (all states)
        self._offers: dict[str, TradeOffer] = {}
        # Aggregate price observations from accepted trades, for the report.
        self._price_observations: list[dict[str, Any]] = []

        self._replay()

    # ─── Inventory helpers (test/sim setup) ────────────────────────────

    def set_inventory(self, agent_id: str, material: str, qty: int) -> None:
        """Seed inventory directly (sim bootstrap / tests).

        Recorded as an ``inventory_set`` event so replay restores the value.
        """
        if qty < 0:
            raise ValueError(f"qty must be >= 0 (got {qty})")
        holdings = self._inventory.setdefault(agent_id, {})
        if qty == 0:
            holdings.pop(material, None)
        else:
            holdings[material] = qty
        self._append_event(
            {
                "action": "inventory_set",
                "agent_id": agent_id,
                "material": material,
                "qty": qty,
                "wall_time": datetime.now(UTC).isoformat(),
            }
        )

    def get_inventory(self, agent_id: str) -> dict[str, int]:
        return dict(self._inventory.get(agent_id, {}))

    # ─── Public API ────────────────────────────────────────────────────

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def price_observations(self) -> list[dict[str, Any]]:
        return list(self._price_observations)

    def propose(
        self,
        *,
        proposer_id: str,
        recipient_id: str,
        give: dict[str, Any] | None = None,
        want: dict[str, Any] | None = None,
        motivation: str | None = None,
        give_containers: list[Any] | None = None,
        want_containers: list[Any] | None = None,
    ) -> TradeOffer | TradeFailure:
        """Record a new pending offer."""
        if proposer_id == recipient_id:
            return TradeFailure(reason="self_trade", detail="proposer and recipient match")
        try:
            give_norm = _normalize_bundle(give, label="give")
            want_norm = _normalize_bundle(want, label="want")
            give_container_refs = _normalize_containers(give_containers, label="give_containers")
            want_container_refs = _normalize_containers(want_containers, label="want_containers")
        except ValueError as exc:
            return TradeFailure(reason="empty_trade", detail=str(exc))

        if not (give_norm or want_norm or give_container_refs or want_container_refs):
            return TradeFailure(
                reason="empty_trade",
                detail="trade must specify at least one give or want item",
            )

        offer = TradeOffer(
            offer_id=str(uuid.uuid4()),
            proposer_id=proposer_id,
            recipient_id=recipient_id,
            give=give_norm,
            want=want_norm,
            give_containers=give_container_refs,
            want_containers=want_container_refs,
            motivation=motivation,
            status="pending",
            created_at=datetime.now(UTC),
        )
        self._offers[offer.offer_id] = offer
        self._append_event(
            {
                "action": "proposed",
                "offer_id": offer.offer_id,
                "proposer_id": offer.proposer_id,
                "recipient_id": offer.recipient_id,
                "give": offer.give,
                "want": offer.want,
                "give_containers": offer.give_containers,
                "want_containers": offer.want_containers,
                "motivation": offer.motivation,
                "wall_time": offer.created_at.isoformat(),
            }
        )
        return offer

    def accept(
        self,
        offer_id: str,
        *,
        accepting_agent_id: str,
        ownership_ledger: Any | None = None,
    ) -> TradeOffer | TradeFailure:
        """Recipient accepts the offer; atomically swap inventories."""
        offer = self._offers.get(offer_id)
        if offer is None:
            return TradeFailure(reason="unknown_offer", offer_id=offer_id)
        if offer.status != "pending":
            return TradeFailure(
                reason="already_resolved",
                offer_id=offer_id,
                detail=f"status={offer.status}",
            )
        if offer.recipient_id != accepting_agent_id:
            return TradeFailure(
                reason="wrong_recipient",
                offer_id=offer_id,
                detail=f"recipient is {offer.recipient_id}",
            )
        if not _has_inventory(self._inventory, offer.proposer_id, offer.give):
            return TradeFailure(
                reason="insufficient_inventory",
                offer_id=offer_id,
                detail=f"{offer.proposer_id} lacks promised give bundle",
            )
        if not _has_inventory(self._inventory, offer.recipient_id, offer.want):
            return TradeFailure(
                reason="insufficient_inventory",
                offer_id=offer_id,
                detail=f"{offer.recipient_id} lacks promised want bundle",
            )

        _apply_inventory_delta(
            self._inventory,
            debit_agent=offer.proposer_id,
            credit_agent=offer.recipient_id,
            bundle=offer.give,
        )
        _apply_inventory_delta(
            self._inventory,
            debit_agent=offer.recipient_id,
            credit_agent=offer.proposer_id,
            bundle=offer.want,
        )

        container_transfers = self._apply_container_transfers(offer, ownership_ledger)

        resolved_at = datetime.now(UTC)
        accepted = offer.model_copy(update={"status": "accepted", "resolved_at": resolved_at})
        self._offers[offer_id] = accepted

        price_observation = self._record_price_observation(accepted)
        self._append_event(
            {
                "action": "accepted",
                "offer_id": offer_id,
                "proposer_id": offer.proposer_id,
                "recipient_id": offer.recipient_id,
                "give": offer.give,
                "want": offer.want,
                "give_containers": offer.give_containers,
                "want_containers": offer.want_containers,
                "motivation": offer.motivation,
                "price_observation": price_observation,
                "container_transfers": container_transfers,
                "wall_time": resolved_at.isoformat(),
            }
        )
        return accepted

    def reject(
        self,
        offer_id: str,
        *,
        accepting_agent_id: str,
        reason: str,
    ) -> TradeOffer | TradeFailure:
        """Recipient declines the offer."""
        offer = self._offers.get(offer_id)
        if offer is None:
            return TradeFailure(reason="unknown_offer", offer_id=offer_id)
        if offer.status != "pending":
            return TradeFailure(
                reason="already_resolved",
                offer_id=offer_id,
                detail=f"status={offer.status}",
            )
        if offer.recipient_id != accepting_agent_id:
            return TradeFailure(
                reason="wrong_recipient",
                offer_id=offer_id,
                detail=f"recipient is {offer.recipient_id}",
            )
        resolved_at = datetime.now(UTC)
        rejected = offer.model_copy(
            update={
                "status": "rejected",
                "resolved_at": resolved_at,
                "reject_reason": reason,
            }
        )
        self._offers[offer_id] = rejected
        self._append_event(
            {
                "action": "rejected",
                "offer_id": offer_id,
                "proposer_id": offer.proposer_id,
                "recipient_id": offer.recipient_id,
                "give": offer.give,
                "want": offer.want,
                "motivation": offer.motivation,
                "reject_reason": reason,
                "wall_time": resolved_at.isoformat(),
            }
        )
        return rejected

    def list_pending(self, agent_id: str) -> list[TradeOffer]:
        """Pending offers awaiting *this* agent's response (creation order)."""
        return [
            o for o in self._offers.values() if o.status == "pending" and o.recipient_id == agent_id
        ]

    def get(self, offer_id: str) -> TradeOffer | None:
        return self._offers.get(offer_id)

    # ─── Internal helpers ──────────────────────────────────────────────

    def _apply_container_transfers(
        self,
        offer: TradeOffer,
        ownership_ledger: Any | None,
    ) -> list[dict[str, Any]]:
        """Release+reclaim each container so ownership follows the trade.

        No-op when ``ownership_ledger`` is None — the trade still completes
        and the inventory bundles swap, but container ownership is unchanged.
        Each transfer is recorded for the event log and the
        :class:`OwnershipLedger` writes its own ``ownership_delta`` rows via
        the existing release/claim path.
        """
        if ownership_ledger is None:
            return []
        transfers: list[dict[str, Any]] = []
        for ref in offer.give_containers:
            transfers.append(
                self._transfer_container(
                    ownership_ledger,
                    target_ref=ref,
                    from_agent=offer.proposer_id,
                    to_agent=offer.recipient_id,
                )
            )
        for ref in offer.want_containers:
            transfers.append(
                self._transfer_container(
                    ownership_ledger,
                    target_ref=ref,
                    from_agent=offer.recipient_id,
                    to_agent=offer.proposer_id,
                )
            )
        return transfers

    @staticmethod
    def _transfer_container(
        ownership_ledger: Any,
        *,
        target_ref: dict[str, Any],
        from_agent: str,
        to_agent: str,
    ) -> dict[str, Any]:
        existing = ownership_ledger.get("container", target_ref)
        released_claim_id: str | None = None
        if existing is not None and existing.owner_agent_id == from_agent:
            released = ownership_ledger.release(existing.claim_id, reason="traded")
            if released is not None:
                released_claim_id = released.claim_id
        new_claim = ownership_ledger.claim(
            owner_agent_id=to_agent,
            target_type="container",
            target_ref=target_ref,
            motivation="received via trade",
        )
        new_claim_id = getattr(new_claim, "claim_id", None)
        return {
            "target_type": "container",
            "target_ref": target_ref,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "released_claim_id": released_claim_id,
            "new_claim_id": new_claim_id,
        }

    def _record_price_observation(self, offer: TradeOffer) -> dict[str, Any]:
        """Emit one price observation per (give_mat, want_mat) pair.

        For the MVP we record raw qty pairs and let the report aggregate —
        a single multi-material trade produces N×M observations so the
        per-pair index is easy to average post-hoc.
        """
        observations: list[dict[str, Any]] = []
        for give_mat, give_qty in offer.give.items():
            for want_mat, want_qty in offer.want.items():
                obs = {
                    "give_material": give_mat,
                    "give_qty": give_qty,
                    "want_material": want_mat,
                    "want_qty": want_qty,
                }
                observations.append(obs)
                self._price_observations.append(obs)
        return {
            "offer_id": offer.offer_id,
            "observations": observations,
        }

    def _append_event(self, record: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:  # pragma: no cover - logging must not break sim
            logger.exception("trade_log: failed to append event")

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
                        logger.warning("trade_log: skipping malformed line %d", line_no)
                        continue
                    self._apply_replay(record)
        except OSError:  # pragma: no cover
            logger.exception("trade_log: failed to replay")

    def _apply_replay(self, record: dict[str, Any]) -> None:
        action = record.get("action")
        if action == "inventory_set":
            agent_id = record.get("agent_id")
            material = record.get("material")
            qty = record.get("qty")
            if not isinstance(agent_id, str) or not isinstance(material, str):
                return
            try:
                qty_int = int(qty)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return
            holdings = self._inventory.setdefault(agent_id, {})
            if qty_int <= 0:
                holdings.pop(material, None)
            else:
                holdings[material] = qty_int
            return

        offer_id = record.get("offer_id")
        if not isinstance(offer_id, str):
            return

        if action == "proposed":
            try:
                created_at = datetime.fromisoformat(record["wall_time"])
            except (KeyError, TypeError, ValueError):
                created_at = datetime.now(UTC)
            try:
                offer = TradeOffer(
                    offer_id=offer_id,
                    proposer_id=record["proposer_id"],
                    recipient_id=record["recipient_id"],
                    give={k: int(v) for k, v in (record.get("give") or {}).items()},
                    want={k: int(v) for k, v in (record.get("want") or {}).items()},
                    give_containers=list(record.get("give_containers") or []),
                    want_containers=list(record.get("want_containers") or []),
                    motivation=record.get("motivation"),
                    status="pending",
                    created_at=created_at,
                )
            except (KeyError, ValueError, TypeError):
                return
            self._offers[offer_id] = offer
            return

        existing = self._offers.get(offer_id)
        if existing is None:
            return

        if action == "accepted" and existing.status == "pending":
            try:
                resolved_at = datetime.fromisoformat(record["wall_time"])
            except (KeyError, TypeError, ValueError):
                resolved_at = datetime.now(UTC)
            _apply_inventory_delta(
                self._inventory,
                debit_agent=existing.proposer_id,
                credit_agent=existing.recipient_id,
                bundle=existing.give,
            )
            _apply_inventory_delta(
                self._inventory,
                debit_agent=existing.recipient_id,
                credit_agent=existing.proposer_id,
                bundle=existing.want,
            )
            self._offers[offer_id] = existing.model_copy(
                update={"status": "accepted", "resolved_at": resolved_at}
            )
            price_observation = record.get("price_observation") or {}
            for obs in price_observation.get("observations", []) or []:
                if isinstance(obs, dict):
                    self._price_observations.append(obs)
            return

        if action == "rejected" and existing.status == "pending":
            try:
                resolved_at = datetime.fromisoformat(record["wall_time"])
            except (KeyError, TypeError, ValueError):
                resolved_at = datetime.now(UTC)
            self._offers[offer_id] = existing.model_copy(
                update={
                    "status": "rejected",
                    "resolved_at": resolved_at,
                    "reject_reason": record.get("reject_reason"),
                }
            )
            return

        if action == "expired" and existing.status == "pending":
            try:
                resolved_at = datetime.fromisoformat(record["wall_time"])
            except (KeyError, TypeError, ValueError):
                resolved_at = datetime.now(UTC)
            self._offers[offer_id] = existing.model_copy(
                update={"status": "expired", "resolved_at": resolved_at}
            )


__all__ = [
    "TradeAction",
    "TradeFailure",
    "TradeFailureReason",
    "TradeLedger",
    "TradeOffer",
    "TradeStatus",
]
