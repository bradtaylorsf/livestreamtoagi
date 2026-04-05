"""Conversation config loader with hot-reload via watchfiles.

Loads config from the database (versioned conversation_param_versions table)
with fallback to config/conversation_config.yaml. Validates through the
ConversationConfig Pydantic model and watches for file changes to hot-reload.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from core.event_bus import event_bus
from core.models import ConversationConfig

if TYPE_CHECKING:
    from core.repos.config_version_repo import ConfigVersionRepo

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "conversation_config.yaml"


class ConfigLoader:
    """Loads, validates, and hot-reloads conversation config from DB or YAML."""

    def __init__(
        self,
        path: str | Path = DEFAULT_CONFIG_PATH,
        config_version_repo: ConfigVersionRepo | None = None,
    ) -> None:
        self._path = Path(path)
        self._config: ConversationConfig | None = None
        self._config_hash: str = ""
        self._watch_task: asyncio.Task[None] | None = None
        self._config_repo = config_version_repo

    @property
    def config(self) -> ConversationConfig:
        """Return the current validated config. Raises if not yet loaded."""
        if self._config is None:
            raise RuntimeError("Config not loaded — call load() first")
        return self._config

    @property
    def config_hash(self) -> str:
        """SHA256 hash (first 16 chars) of the current config file."""
        return self._config_hash

    def load(self) -> ConversationConfig:
        """Read YAML from disk, validate, and store atomically.

        Raises on invalid config (file not found, parse error, validation).
        """
        raw_bytes = self._path.read_bytes()
        raw = yaml.safe_load(raw_bytes)
        if not isinstance(raw, dict):
            raise ValueError(
                f"Config file must be a YAML mapping, got {type(raw).__name__}"
            )

        config = ConversationConfig(**raw)
        file_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]

        # Atomic swap
        self._config = config
        self._config_hash = file_hash

        logger.info(
            "Loaded conversation config (hash=%s) from %s",
            file_hash,
            self._path,
        )
        return config

    async def load_from_db(self) -> ConversationConfig | None:
        """Try to load conversation config from the versioned DB table.

        Returns the config if successful, None if no DB config exists or
        the repo is not configured.
        """
        if self._config_repo is None:
            return None

        try:
            version = await self._config_repo.get_active_conversation_params()
            if version is None:
                return None

            config = ConversationConfig(**version.params)
            file_hash = hashlib.sha256(
                str(version.params).encode()
            ).hexdigest()[:16]

            self._config = config
            self._config_hash = file_hash

            logger.info(
                "Loaded conversation config from DB (version=%d, hash=%s)",
                version.version,
                file_hash,
            )
            return config
        except Exception:
            logger.warning(
                "Failed to load conversation config from DB, "
                "will fall back to YAML",
                exc_info=True,
            )
            return None

    async def start_watching(self) -> None:
        """Start an async background task that watches for file changes."""
        if self._watch_task is not None:
            return
        self._watch_task = asyncio.create_task(self._watch_loop())
        logger.info("Started watching %s for changes", self._path)

    async def stop_watching(self) -> None:
        """Cancel the file-watcher task."""
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None
            logger.info("Stopped watching %s", self._path)

    async def _watch_loop(self) -> None:
        """Watch the config file for changes and reload on modification."""
        from watchfiles import awatch

        try:
            async for _changes in awatch(self._path):
                await self._try_reload()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Config watcher crashed")

    async def _try_reload(self) -> None:
        """Attempt to reload config; on failure, keep previous valid config."""
        previous_hash = self._config_hash
        try:
            self.load()
        except Exception:
            logger.exception(
                "Invalid config change detected — keeping previous config (hash=%s)",
                previous_hash,
            )
            return

        if self._config_hash != previous_hash:
            logger.info(
                "Config reloaded: %s -> %s", previous_hash, self._config_hash
            )
            await event_bus.emit(
                "config_reloaded",
                {
                    "previous_hash": previous_hash,
                    "new_hash": self._config_hash,
                    "path": str(self._path),
                },
            )
