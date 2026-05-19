"""Pure perception snapshot helpers for E6-6 (#561).

The Node observe action reports a full ``perception_snapshot`` through the
existing ``perception.report`` bridge verb. This module turns that raw
observation into the typed bridge contract model without depending on the event
bus, database, Redis, or Minecraft.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from core.bridge.contract import PerceptionSnapshot
from core.embodiment.building import _normalize_block_type

_ENTITY_KINDS = {"player", "mob", "item", "object"}
_SCOPES = {"pose", "nearby_blocks", "entities", "inventory", "all"}


def _normalized_id(value: Any) -> str | None:
    return _normalize_block_type(value)


def _normalized_optional_id(value: Any) -> str | None:
    if value is None:
        return None
    return _normalized_id(value)


def _normalized_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_dimension(value: Any) -> Any:
    normalized = _normalized_id(value)
    return normalized or value


def _normalize_pose(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    pose = dict(value)
    if "dimension" in pose:
        pose["dimension"] = _normalized_dimension(pose["dimension"])
    return pose


def _normalize_block(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    block = dict(value)
    if "block_type" in block:
        block["block_type"] = _normalized_id(block["block_type"])
    return block


def _normalize_entity(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    entity = dict(value)
    kind = _normalized_text(entity.get("kind"))
    if kind is not None:
        normalized_kind = kind.lower()
        entity["kind"] = normalized_kind if normalized_kind in _ENTITY_KINDS else kind
    if "name" in entity:
        name = _normalized_text(entity["name"])
        entity["name"] = (
            name
            if entity.get("kind") == "player"
            else (_normalized_optional_id(name) or name)
        )
    if "entity_id" in entity:
        entity["entity_id"] = _normalized_text(entity["entity_id"])
    return entity


def _normalize_inventory_item(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    item = dict(value)
    if "item_id" in item:
        item["item_id"] = _normalized_id(item["item_id"])
    return item


def _normalize_equipment(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {str(slot): _normalized_optional_id(item) for slot, item in value.items()}


def _normalize_inventory(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    inventory = dict(value)
    inventory["items"] = [
        _normalize_inventory_item(item) for item in inventory.get("items", [])
    ]
    inventory["equipment"] = _normalize_equipment(inventory.get("equipment", {}))
    return inventory


def _normalize_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = dict(value)
    snapshot["pose"] = _normalize_pose(snapshot.get("pose"))
    snapshot["nearby_blocks"] = [
        _normalize_block(block) for block in snapshot.get("nearby_blocks", [])
    ]
    snapshot["entities"] = [_normalize_entity(entity) for entity in snapshot.get("entities", [])]
    snapshot["inventory"] = _normalize_inventory(snapshot.get("inventory"))
    scope = _normalized_text(snapshot.get("scope"))
    if scope is not None:
        normalized_scope = scope.lower()
        snapshot["scope"] = normalized_scope if normalized_scope in _SCOPES else scope
    return snapshot


def build_perception_snapshot(
    observations: Iterable[Mapping[str, Any]],
) -> PerceptionSnapshot | None:
    """Return the typed snapshot observation, if present and schema-valid.

    ``PerceptionReportRequest.observations`` remains a raw list for backward
    compatibility with earlier pose/block/structure reports. E6-6 snapshots are
    identified by ``type == "perception_snapshot"`` and validated separately.
    """
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        if observation.get("type") != "perception_snapshot":
            continue
        try:
            return PerceptionSnapshot.model_validate(_normalize_snapshot(observation))
        except (TypeError, ValidationError, ValueError):
            return None
    return None


def is_schema_valid_snapshot(observation: Mapping[str, Any]) -> bool:
    """Return whether *observation* is a schema-valid perception snapshot."""
    return build_perception_snapshot([observation]) is not None
