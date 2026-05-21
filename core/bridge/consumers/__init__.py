"""Event bus consumers for bridge-originated events."""

from __future__ import annotations

from core.bridge.consumers.perception_action_memory import (
    format_action_result,
    format_observations,
    on_bridge_action_result,
    on_bridge_perception,
    register_memory_consumer,
    unregister_memory_consumer,
)
from core.bridge.consumers.scene_memory import (
    SceneMemoryConsumer,
    register_scene_memory_consumer,
    unregister_scene_memory_consumer,
)

__all__ = [
    "SceneMemoryConsumer",
    "format_action_result",
    "format_observations",
    "on_bridge_action_result",
    "on_bridge_perception",
    "register_memory_consumer",
    "register_scene_memory_consumer",
    "unregister_memory_consumer",
    "unregister_scene_memory_consumer",
]
