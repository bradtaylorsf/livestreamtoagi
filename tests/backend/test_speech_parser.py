"""Tests for core.speech_parser — dialogue/action separation."""

from core.speech_parser import ParsedSpeech, parse_speech


class TestParseSpeech:
    """Unit tests for parse_speech()."""

    def test_plain_dialogue_no_tags(self):
        result = parse_speech("Yeah, that's not going to ship.")
        assert result.dialogue == "Yeah, that's not going to ship."
        assert result.actions == []
        assert result.raw == "Yeah, that's not going to ship."

    def test_single_action_with_dialogue(self):
        text = "[action]leans back in chair[/action] Well, that won't ship."
        result = parse_speech(text)
        assert result.dialogue == "Well, that won't ship."
        assert result.actions == ["leans back in chair"]
        assert result.raw == text

    def test_action_mid_sentence(self):
        text = "I mean REALLY, does anyone read the docs? [action]gestures at whiteboard[/action]"
        result = parse_speech(text)
        assert result.dialogue == "I mean REALLY, does anyone read the docs?"
        assert result.actions == ["gestures at whiteboard"]

    def test_multiple_actions(self):
        text = (
            "[action]pulls up terminal[/action] Let me show you. "
            "[action]types furiously[/action] See? Line 47."
        )
        result = parse_speech(text)
        assert result.dialogue == "Let me show you. See? Line 47."
        assert result.actions == ["pulls up terminal", "types furiously"]

    def test_action_only_no_dialogue(self):
        text = "[action]waves silently[/action]"
        result = parse_speech(text)
        assert result.dialogue == ""
        assert result.actions == ["waves silently"]
        assert result.raw == text

    def test_empty_string(self):
        result = parse_speech("")
        assert result.dialogue == ""
        assert result.actions == []
        assert result.raw == ""

    def test_case_insensitive_tags(self):
        text = "[ACTION]sighs dramatically[/ACTION] Fine, I'll review it."
        result = parse_speech(text)
        assert result.dialogue == "Fine, I'll review it."
        assert result.actions == ["sighs dramatically"]

    def test_malformed_unclosed_tag_passes_through(self):
        text = "[action]adjusts glasses This won't get stripped."
        result = parse_speech(text)
        assert result.dialogue == text
        assert result.actions == []

    def test_whitespace_between_actions_collapsed(self):
        text = "[action]stands up[/action]  [action]walks to board[/action] Okay, listen."
        result = parse_speech(text)
        assert result.dialogue == "Okay, listen."
        assert result.actions == ["stands up", "walks to board"]

    def test_frozen_dataclass(self):
        result = parse_speech("Hello")
        assert isinstance(result, ParsedSpeech)
        # frozen=True means assignment raises
        try:
            result.dialogue = "changed"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass
