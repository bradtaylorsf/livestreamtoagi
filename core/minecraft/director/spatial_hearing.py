"""Deterministic 3D spatial hearing for Minecraft Director V2.

This mirrors the useful concepts from ``core.conversation.proximity``:
nearby agents can participate, farther agents can observe/eavesdrop, and
conversation size is bounded. The legacy manager is chunk/Redis based and uses
weighted randomness; Minecraft scenes need in-process 3D positions and stable
ordering so the Director V2 prompt fanout is predictable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from core.bridge.contract import Vec3


@dataclass(frozen=True)
class SpatialHearingConfig:
    """Tunable radii and automatic participant cap for scene grouping."""

    default_hearing_radius_blocks: float = 16.0
    event_type_radius_overrides: Mapping[str, float] = field(default_factory=dict)
    observer_radius_blocks: float = 48.0
    max_participants_per_scene: int = 4

    def hearing_radius_for(self, event_type: str | None = None) -> float:
        if event_type is None:
            return self.default_hearing_radius_blocks
        return self.event_type_radius_overrides.get(
            event_type,
            self.default_hearing_radius_blocks,
        )


@dataclass(frozen=True)
class AgentPose:
    """Last known Minecraft pose for an agent."""

    agent_id: str
    position: Vec3
    dimension: str
    last_seen_ts: int


def distance_blocks(a: Vec3, b: Vec3) -> float:
    """Return Euclidean distance between two Minecraft positions."""

    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


class SpatialHearingAdapter:
    """Classify nearby Minecraft agents into participants and observers."""

    def __init__(self, config: SpatialHearingConfig | None = None) -> None:
        self.config = config or SpatialHearingConfig()
        self._poses: dict[str, AgentPose] = {}

    @property
    def poses(self) -> Mapping[str, AgentPose]:
        return self._poses

    def update_pose(self, agent_id: str, pose: AgentPose) -> None:
        canonical_id = _canonical_agent_id(agent_id)
        self._poses[canonical_id] = AgentPose(
            agent_id=canonical_id,
            position=pose.position,
            dimension=pose.dimension,
            last_seen_ts=pose.last_seen_ts,
        )

    def get_pose(self, agent_id: str) -> AgentPose | None:
        return self._poses.get(_canonical_agent_id(agent_id))

    def agents_within(self, origin: Vec3, dimension: str, radius: float) -> list[str]:
        """Return same-dimension agents within *radius*, sorted by distance then id."""

        ranked = self._ranked_known_agents(origin, dimension, radius)
        return [agent_id for agent_id, _distance in ranked]

    def classify_listeners(
        self,
        origin: Vec3,
        dimension: str,
        *,
        direct_addressees: set[str],
        event_type: str | None = None,
    ) -> tuple[list[str], list[str]]:
        """Return ``(participants, observers)`` for a scene event.

        Direct addressees are required participants even when outside the
        hearing radius or when their latest pose is unknown. The configured cap
        applies to automatic nearby participants, not explicit addressees.
        """

        direct = {_canonical_agent_id(agent_id) for agent_id in direct_addressees}
        hearing_radius = self.config.hearing_radius_for(event_type)
        observer_radius = max(self.config.observer_radius_blocks, hearing_radius)

        automatic_slots = max(self.config.max_participants_per_scene - len(direct), 0)
        automatic = [
            agent_id
            for agent_id, _distance in self._ranked_known_agents(
                origin,
                dimension,
                hearing_radius,
            )
            if agent_id not in direct
        ][:automatic_slots]

        participants_set = set(automatic) | direct
        participants = self._sort_ids_by_distance(origin, participants_set)

        observer_candidates = {
            agent_id
            for agent_id, _distance in self._ranked_known_agents(origin, dimension, observer_radius)
            if agent_id not in participants_set
        }
        observers = self._sort_ids_by_distance(origin, observer_candidates)
        return participants, observers

    def _ranked_known_agents(
        self,
        origin: Vec3,
        dimension: str,
        radius: float,
    ) -> list[tuple[str, float]]:
        ranked: list[tuple[str, float]] = []
        for agent_id, pose in self._poses.items():
            if pose.dimension != dimension:
                continue
            distance = distance_blocks(origin, pose.position)
            if distance <= radius:
                ranked.append((agent_id, distance))
        return sorted(ranked, key=lambda item: (item[1], item[0]))

    def _sort_ids_by_distance(self, origin: Vec3, agent_ids: set[str]) -> list[str]:
        def key(agent_id: str) -> tuple[float, str]:
            pose = self._poses.get(agent_id)
            if pose is None:
                return math.inf, agent_id
            return distance_blocks(origin, pose.position), agent_id

        return sorted(agent_ids, key=key)


def _canonical_agent_id(agent_id: str) -> str:
    return agent_id.strip().lower()

