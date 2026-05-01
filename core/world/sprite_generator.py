"""Sprite sheet generator using PixelLab for all agent assets."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.world.pixellab_client import PixelLabClient

logger = logging.getLogger(__name__)

SPRITES_DIR = Path("frontend/assets/sprites")
PORTRAITS_DIR = Path("frontend/assets/portraits")

# 7 main agents at 32x32, Alpha wolf at 24x24
AGENT_ANIMATIONS = [
    "idle",
    "walk_up",
    "walk_down",
    "walk_left",
    "walk_right",
    "talking",
    "thinking",
    "building",
]

ALPHA_ANIMATIONS = [
    "idle",
    "running",
    "carrying",
    "confused",
    "celebrate",
    "sleeping",
]

AGENT_SPRITE_PROMPTS: dict[str, str] = {
    "vera": (
        "Female character. Navy blue blazer over white shirt. Small glasses. "
        "Brown hair in a neat bun. Holding a clipboard in idle pose. "
        "Expression: slightly concerned but determined. Accent color: navy blue."
    ),
    "rex": (
        "Male character. Dark grey hoodie, hood down. Messy dark hair. "
        "Slight frown / neutral expression. Accent color: terminal green (#00FF00). "
        "Accessories: coffee cup in idle pose."
    ),
    "aurora": (
        "Female character. Colorful outfit — purple top with gold accents. "
        "Small beret tilted to one side. Paint-stained hands. Warm expression, slight smile. "
        "Accent colors: purple, pink, and gold."
    ),
    "pixel": (
        "Male character. Light blue t-shirt with small pixelated heart design. "
        "Headphones around neck. Bright eyes, excited expression. "
        "Accent colors: light blue and orange."
    ),
    "fork": (
        "Male character. All black clothing — black t-shirt, black pants. "
        "Slightly disheveled hair. Small Tux penguin pin on shirt. "
        "Neutral-to-skeptical expression. Accent colors: black, dark green, amber."
    ),
    "sentinel": (
        "Male character. Grey vest over white shirt, small red tie. "
        "Slightly hunched posture. Worried expression — raised eyebrows. "
        "Accent colors: grey and warning red."
    ),
    "grok": (
        "Male character. Black leather jacket, dark sunglasses worn on face. "
        "Confident posture — slightly leaning back. Smirk expression. "
        "Accent colors: black and electric blue (#1DA1F2)."
    ),
}

ALPHA_SPRITE_PROMPT = (
    "Small wolf / dog character. Grey-white fur with lighter belly. "
    "Large eyes proportional to body (cute/chibi style). Pointed ears, bushy tail. "
    "Friendly, eager expression."
)

MAIN_AGENTS = ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]


class SpriteGenerator:
    """Generates sprite sheets and portraits for all agents via PixelLab."""

    def __init__(
        self,
        pixellab: PixelLabClient,
        sprites_dir: Path = SPRITES_DIR,
        portraits_dir: Path = PORTRAITS_DIR,
    ) -> None:
        self._pixellab = pixellab
        self._sprites_dir = sprites_dir
        self._portraits_dir = portraits_dir

    def is_cached(self, agent_id: str) -> bool:
        """Check if sprite sheet and metadata exist for an agent."""
        agent_dir = self._sprites_dir / agent_id
        return (agent_dir / "metadata.json").exists() and (agent_dir / "spritesheet.png").exists()

    def is_portrait_cached(self, agent_id: str) -> bool:
        """Check if portrait exists for an agent."""
        return (self._portraits_dir / f"{agent_id}.png").exists()

    async def generate_all(self) -> list[dict[str, Any]]:
        """Generate sprite sheets and portraits for all agents.

        Returns list of metadata dicts, one per agent.
        """
        results = []
        for agent_id in MAIN_AGENTS:
            meta = await self.generate_agent(agent_id)
            results.append(meta)

        alpha_meta = await self.generate_alpha()
        results.append(alpha_meta)

        # Generate portraits for main agents
        for agent_id in MAIN_AGENTS:
            await self.generate_portrait(agent_id)

        return results

    async def generate_agent(self, agent_id: str) -> dict[str, Any]:
        """Generate sprite sheet for a single main agent (32x32)."""
        agent_dir = self._sprites_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = agent_dir / "metadata.json"
        if self.is_cached(agent_id):
            logger.info("Sprite cached for %s, skipping", agent_id)
            return json.loads(metadata_path.read_text())

        prompt = AGENT_SPRITE_PROMPTS.get(agent_id, "")
        frame_size = "32x32"
        frame_count = len(AGENT_ANIMATIONS)

        sheet_prompt = (
            f"16-bit pixel art, RPG-style top-down perspective. "
            f"Chibi proportions: large head, small body, ~3 heads tall. "
            f"{prompt} "
            f"Sprite sheet: {frame_count} animation frames arranged horizontally. "
            f"Animations: {', '.join(AGENT_ANIMATIONS)}."
        )

        result = await self._pixellab.generate_sprite_sheet(
            prompt=sheet_prompt,
            frame_count=frame_count,
            frame_size=frame_size,
            agent_id="system",
        )

        # Move sprite sheet to expected location
        src = Path(result["local_path"])
        dest = agent_dir / "spritesheet.png"
        if src.exists() and src != dest:
            src.rename(dest)

        metadata = {
            "agent_id": agent_id,
            "frame_size": 32,
            "frame_count": frame_count,
            "animations": {name: {"start": i, "end": i} for i, name in enumerate(AGENT_ANIMATIONS)},
            "spritesheet": str(dest),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2))
        logger.info("Generated sprite sheet for %s", agent_id)
        return metadata

    async def generate_alpha(self) -> dict[str, Any]:
        """Generate sprite sheet for Alpha wolf (24x24)."""
        agent_dir = self._sprites_dir / "alpha"
        agent_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = agent_dir / "metadata.json"
        if self.is_cached("alpha"):
            logger.info("Sprite cached for alpha, skipping")
            return json.loads(metadata_path.read_text())

        frame_size = "24x24"
        frame_count = len(ALPHA_ANIMATIONS)

        sheet_prompt = (
            f"16-bit pixel art, 24x24 sprite, RPG-style top-down. "
            f"Simple, cute wolf design. "
            f"{ALPHA_SPRITE_PROMPT} "
            f"Sprite sheet: {frame_count} animation frames arranged horizontally. "
            f"Animations: {', '.join(ALPHA_ANIMATIONS)}."
        )

        result = await self._pixellab.generate_sprite_sheet(
            prompt=sheet_prompt,
            frame_count=frame_count,
            frame_size=frame_size,
            agent_id="system",
        )

        src = Path(result["local_path"])
        dest = agent_dir / "spritesheet.png"
        if src.exists() and src != dest:
            src.rename(dest)

        metadata = {
            "agent_id": "alpha",
            "frame_size": 24,
            "frame_count": frame_count,
            "animations": {name: {"start": i, "end": i} for i, name in enumerate(ALPHA_ANIMATIONS)},
            "spritesheet": str(dest),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2))
        logger.info("Generated sprite sheet for alpha")
        return metadata

    async def generate_portrait(self, agent_id: str) -> dict[str, Any]:
        """Generate 256x256 character portrait for website/social use."""
        self._portraits_dir.mkdir(parents=True, exist_ok=True)

        portrait_path = self._portraits_dir / f"{agent_id}.png"
        if portrait_path.exists():
            logger.info("Portrait cached for %s, skipping", agent_id)
            return {"agent_id": agent_id, "local_path": str(portrait_path)}

        prompt_desc = AGENT_SPRITE_PROMPTS.get(agent_id, "")
        prompt = (
            f"Character portrait, pixel art style, detailed face and upper body. "
            f"{prompt_desc} "
            f"256x256 resolution, clean pixel art, warm lighting."
        )

        result = await self._pixellab.generate_asset(
            prompt=prompt,
            style="portrait",
            size="256x256",
            agent_id="system",
        )

        src = Path(result["local_path"])
        if src.exists() and src != portrait_path:
            src.rename(portrait_path)

        logger.info("Generated portrait for %s", agent_id)
        return {"agent_id": agent_id, "local_path": str(portrait_path)}
