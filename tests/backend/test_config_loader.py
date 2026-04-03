"""Tests for core.config_loader — conversation config loading and hot-reload."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.config_loader import ConfigLoader
from core.models import ConversationConfig

# ── Helpers ────────────────────────────────────────────


def _load_default_yaml() -> dict:
    """Load the shipped conversation_config.yaml as a dict."""
    with open("config/conversation_config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


# ── Unit tests ─────────────────────────────────────────


class TestValidConfigLoads:
    """Valid config loads successfully."""

    def test_load_default_config(self) -> None:
        loader = ConfigLoader()
        config = loader.load()
        assert isinstance(config, ConversationConfig)
        assert loader.config is config

    def test_all_sections_present(self) -> None:
        loader = ConfigLoader()
        config = loader.load()
        assert config.selection_weights is not None
        assert config.timing is not None
        assert config.energy is not None
        assert config.interrupts is not None
        assert config.proximity is not None
        assert config.triggers is not None
        assert config.topics is not None
        assert config.adjacency is not None
        assert config.logging is not None

    def test_selection_weights_values(self) -> None:
        loader = ConfigLoader()
        config = loader.load()
        w = config.selection_weights
        assert w.time_since_spoke == 0.30
        assert w.topic_relevance == 0.30
        assert w.chattiness == 0.15
        assert w.adjacency_fit == 0.15
        assert w.random_jitter == 0.10


class TestInvalidWeightsRejected:
    """Invalid weights (not summing to 1.0) are rejected."""

    def test_weights_sum_too_high(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        data["selection_weights"]["random_jitter"] = 0.50  # sum > 1.0
        _write_yaml(tmp_path / "bad.yaml", data)

        loader = ConfigLoader(path=tmp_path / "bad.yaml")
        with pytest.raises(ValueError, match="must sum to 1.0"):
            loader.load()

    def test_weights_sum_too_low(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        data["selection_weights"]["random_jitter"] = 0.01  # sum < 1.0
        _write_yaml(tmp_path / "bad.yaml", data)

        loader = ConfigLoader(path=tmp_path / "bad.yaml")
        with pytest.raises(ValueError, match="must sum to 1.0"):
            loader.load()


class TestMissingFieldsRejected:
    """Missing required fields are rejected."""

    def test_missing_selection_weights(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        del data["selection_weights"]
        _write_yaml(tmp_path / "bad.yaml", data)

        loader = ConfigLoader(path=tmp_path / "bad.yaml")
        with pytest.raises(ValidationError):
            loader.load()

    def test_missing_timing(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        del data["timing"]
        _write_yaml(tmp_path / "bad.yaml", data)

        loader = ConfigLoader(path=tmp_path / "bad.yaml")
        with pytest.raises(ValidationError):
            loader.load()

    def test_missing_energy(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        del data["energy"]
        _write_yaml(tmp_path / "bad.yaml", data)

        loader = ConfigLoader(path=tmp_path / "bad.yaml")
        with pytest.raises(ValidationError):
            loader.load()


class TestConfigHashDeterministic:
    """Config hash is deterministic (same content -> same hash)."""

    def test_hash_matches_sha256(self) -> None:
        loader = ConfigLoader()
        loader.load()

        raw_bytes = Path("config/conversation_config.yaml").read_bytes()
        expected = hashlib.sha256(raw_bytes).hexdigest()[:16]
        assert loader.config_hash == expected

    def test_hash_changes_on_content_change(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path = tmp_path / "cfg.yaml"
        _write_yaml(path, data)

        loader = ConfigLoader(path=path)
        loader.load()
        hash1 = loader.config_hash

        # Change a value
        data["timing"]["min_pause_seconds"] = 999.0
        _write_yaml(path, data)
        loader.load()
        hash2 = loader.config_hash

        assert hash1 != hash2

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path1 = tmp_path / "a.yaml"
        path2 = tmp_path / "b.yaml"
        # Write identical bytes
        content = yaml.dump(data)
        path1.write_text(content)
        path2.write_text(content)

        loader1 = ConfigLoader(path=path1)
        loader1.load()
        loader2 = ConfigLoader(path=path2)
        loader2.load()

        assert loader1.config_hash == loader2.config_hash


class TestHotReload:
    """Hot-reload replaces config on file change."""

    async def test_reload_on_file_change(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path = tmp_path / "cfg.yaml"
        _write_yaml(path, data)

        loader = ConfigLoader(path=path)
        loader.load()
        original_hash = loader.config_hash
        assert loader.config.timing.min_pause_seconds == 2.0

        # Modify and trigger reload
        data["timing"]["min_pause_seconds"] = 5.0
        _write_yaml(path, data)

        await loader._try_reload()

        assert loader.config.timing.min_pause_seconds == 5.0
        assert loader.config_hash != original_hash

    async def test_start_stop_watching(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path = tmp_path / "cfg.yaml"
        _write_yaml(path, data)

        loader = ConfigLoader(path=path)
        loader.load()

        await loader.start_watching()
        assert loader._watch_task is not None

        await loader.stop_watching()
        assert loader._watch_task is None


class TestInvalidReloadPreservesPrevious:
    """Invalid reload preserves previous valid config."""

    async def test_bad_reload_keeps_old_config(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path = tmp_path / "cfg.yaml"
        _write_yaml(path, data)

        loader = ConfigLoader(path=path)
        loader.load()
        good_hash = loader.config_hash
        good_config = loader.config

        # Write invalid config (weights don't sum to 1.0)
        data["selection_weights"]["random_jitter"] = 0.99
        _write_yaml(path, data)

        await loader._try_reload()

        # Should still have the old valid config
        assert loader.config_hash == good_hash
        assert loader.config is good_config

    async def test_bad_yaml_keeps_old_config(self, tmp_path: Path) -> None:
        data = _load_default_yaml()
        path = tmp_path / "cfg.yaml"
        _write_yaml(path, data)

        loader = ConfigLoader(path=path)
        loader.load()
        good_hash = loader.config_hash

        # Write invalid YAML
        path.write_text("{{{{invalid yaml!!!!")

        await loader._try_reload()

        assert loader.config_hash == good_hash


class TestConfigNotLoadedError:
    """Accessing config before load() raises RuntimeError."""

    def test_config_property_raises_before_load(self) -> None:
        loader = ConfigLoader()
        with pytest.raises(RuntimeError, match="not loaded"):
            _ = loader.config

    def test_hash_empty_before_load(self) -> None:
        loader = ConfigLoader()
        assert loader.config_hash == ""
