"""Tests for the variable pause/pacing system."""

from __future__ import annotations

from unittest.mock import patch

from core.conversation.pacing import calculate_pause
from core.models import PauseMultipliers, TimingConfig

# Shared test config matching the spec defaults
_MULTIPLIERS = PauseMultipliers(
    after_question=0.5,
    after_statement=1.0,
    after_interrupt=0.3,
    after_joke=1.5,
    after_emotional=1.3,
)

_CONFIG = TimingConfig(
    min_pause_seconds=2.0,
    max_pause_seconds=8.0,
    pause_strategy="weighted",
    pause_multipliers=_MULTIPLIERS,
)


def _fixed_config() -> TimingConfig:
    return TimingConfig(
        min_pause_seconds=2.0,
        max_pause_seconds=8.0,
        pause_strategy="fixed",
        pause_multipliers=_MULTIPLIERS,
    )


def _random_config() -> TimingConfig:
    return TimingConfig(
        min_pause_seconds=2.0,
        max_pause_seconds=8.0,
        pause_strategy="random",
        pause_multipliers=_MULTIPLIERS,
    )


class TestWeightedStrategy:
    """Weighted strategy applies content-based multipliers."""

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_question_gets_shorter_pause(self, _mock: object) -> None:
        result = calculate_pause("What do you think?", _CONFIG)
        assert result == 2.5  # 5.0 * 0.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_joke_gets_longer_pause(self, _mock: object) -> None:
        result = calculate_pause("That was great haha", _CONFIG)
        assert result == 7.5  # 5.0 * 1.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_emotional_gets_moderate_pause(self, _mock: object) -> None:
        result = calculate_pause("I feel like we should talk", _CONFIG)
        assert result == 6.5  # 5.0 * 1.3

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_statement_gets_normal_pause(self, _mock: object) -> None:
        result = calculate_pause("The code is ready.", _CONFIG)
        assert result == 5.0  # 5.0 * 1.0

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_interrupt_gets_shortest_pause(self, _mock: object) -> None:
        result = calculate_pause("Wait, I have an idea!", _CONFIG, is_interrupt=True)
        assert result == 2.0  # 5.0 * 0.3 = 1.5 → clamped to min 2.0


class TestClamping:
    """Results are always clamped within [min, max]."""

    @patch("core.conversation.pacing.random.uniform", return_value=7.0)
    def test_clamped_to_max(self, _mock: object) -> None:
        # 7.0 * 1.5 = 10.5 → clamped to 8.0
        result = calculate_pause("lol that's hilarious", _CONFIG)
        assert result == 8.0

    @patch("core.conversation.pacing.random.uniform", return_value=3.0)
    def test_clamped_to_min(self, _mock: object) -> None:
        # 3.0 * 0.3 = 0.9 → clamped to 2.0
        result = calculate_pause("Hey!", _CONFIG, is_interrupt=True)
        assert result == 2.0


class TestFixedStrategy:
    """Fixed strategy returns constant (min + max) / 2."""

    def test_returns_average(self) -> None:
        config = _fixed_config()
        result = calculate_pause("Anything here.", config)
        assert result == 5.0  # (2.0 + 8.0) / 2

    def test_ignores_content_type(self) -> None:
        config = _fixed_config()
        assert calculate_pause("Really?", config) == 5.0
        assert calculate_pause("haha nice", config) == 5.0
        assert calculate_pause("I feel sad", config) == 5.0


class TestRandomStrategy:
    """Random strategy returns uniform value within range."""

    def test_within_range(self) -> None:
        config = _random_config()
        for _ in range(100):
            result = calculate_pause("Test message.", config)
            assert 2.0 <= result <= 8.0

    @patch("core.conversation.pacing.random.uniform", return_value=4.2)
    def test_uses_uniform_distribution(self, _mock: object) -> None:
        config = _random_config()
        result = calculate_pause("Test message.", config)
        assert result == 4.2


class TestContentDetection:
    """Content type detection works correctly."""

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_question_mark_detection(self, _mock: object) -> None:
        result = calculate_pause("Is this working?", _CONFIG)
        assert result == 2.5  # question multiplier

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_lol_detection(self, _mock: object) -> None:
        result = calculate_pause("That was so funny lol", _CONFIG)
        assert result == 7.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_lmao_detection(self, _mock: object) -> None:
        result = calculate_pause("lmao I can't believe it", _CONFIG)
        assert result == 7.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_worry_detection(self, _mock: object) -> None:
        result = calculate_pause("I worry about the budget", _CONFIG)
        assert result == 6.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_scared_detection(self, _mock: object) -> None:
        result = calculate_pause("I'm scared of failing", _CONFIG)
        assert result == 6.5

    @patch("core.conversation.pacing.random.uniform", return_value=5.0)
    def test_interrupt_takes_priority(self, _mock: object) -> None:
        # Even with a question mark, interrupt flag wins
        result = calculate_pause("What?", _CONFIG, is_interrupt=True)
        assert result == 2.0  # 5.0 * 0.3 = 1.5 → clamped to 2.0
