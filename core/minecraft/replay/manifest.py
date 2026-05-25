"""``ReplayManifest`` — index of artifacts produced by one replay run."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScreenshotEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    milestone: str
    sim_time: float
    decision_log_row_idx: int
    status: str
    label: str
    intent_id: str | None = None


class ReplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sim_folder: str
    output_dir: str
    started_at: datetime
    finished_at: datetime | None = None
    world_profile: str
    speed_multiplier: float = 1.0
    screenshot_milestones: list[str] = Field(default_factory=list)
    screenshots: list[ScreenshotEntry] = Field(default_factory=list)
    events_replayed_count: int = 0
    build_scripts_executed: list[str] = Field(default_factory=list)
    chat_events_replayed: int = 0
    bridge_kind: str = "fake"
    dry_run: bool = True

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_path(cls, path: Path) -> ReplayManifest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def to_jsonable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = ["ReplayManifest", "ScreenshotEntry"]
