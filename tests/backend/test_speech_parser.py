"""Tests for core.speech_parser — dialogue/action separation."""

from core.speech_parser import ParsedSpeech, parse_speech, parse_speech_segments, strip_markdown


class TestStripMarkdown:
    """Unit tests for strip_markdown()."""

    def test_strips_bold_asterisks(self):
        assert strip_markdown("**Hello** world") == "Hello world"

    def test_strips_bold_underscores(self):
        assert strip_markdown("__Hello__ world") == "Hello world"

    def test_strips_italic_asterisks(self):
        assert strip_markdown("*italic* text") == "italic text"

    def test_strips_italic_underscores(self):
        assert strip_markdown("_italic_ text") == "italic text"

    def test_strips_inline_code(self):
        assert strip_markdown("`code` here") == "code here"

    def test_strips_headers(self):
        assert strip_markdown("## Section\nsome text") == "Section\nsome text"

    def test_plain_text_unchanged(self):
        assert strip_markdown("Plain text, no markdown.") == "Plain text, no markdown."

    def test_bold_before_italic_precedence(self):
        # **text** should not leave stray * that then matches *text*
        result = strip_markdown("**bold** and *italic*")
        assert result == "bold and italic"

    def test_empty_string(self):
        assert strip_markdown("") == ""

    def test_stray_asterisks_removed(self):
        assert strip_markdown("hello * there") == "hello  there"


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

    def test_markdown_stripped_from_dialogue(self):
        text = "**Breaking news:** we are *almost* there!"
        result = parse_speech(text)
        assert result.dialogue == "Breaking news: we are almost there!"
        assert result.raw == text

    def test_frozen_dataclass(self):
        result = parse_speech("Hello")
        assert isinstance(result, ParsedSpeech)
        # frozen=True means assignment raises
        try:
            result.dialogue = "changed"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass


class TestParseSpeechSegments:
    """Unit tests for parse_speech_segments()."""

    def test_no_actions_single_segment(self):
        segments = parse_speech_segments("Hello everyone!")
        assert segments == [("Hello everyone!", None)]

    def test_action_between_two_segments(self):
        text = "Hi! [action]waves[/action] How are you?"
        segments = parse_speech_segments(text)
        assert segments == [("Hi!", None), ("How are you?", "waves")]

    def test_leading_action(self):
        text = "[action]pulls up terminal[/action] Let me show you."
        segments = parse_speech_segments(text)
        assert segments == [("Let me show you.", "pulls up terminal")]

    def test_trailing_action_dropped(self):
        # Action at end with no following dialogue is silently dropped
        text = "Okay! [action]waves goodbye[/action]"
        segments = parse_speech_segments(text)
        assert segments == [("Okay!", None)]

    def test_multiple_actions(self):
        text = (
            "First. [action]pauses[/action] Second. [action]nods[/action] Third."
        )
        segments = parse_speech_segments(text)
        assert segments == [
            ("First.", None),
            ("Second.", "pauses"),
            ("Third.", "nods"),
        ]

    def test_action_only_text_returns_empty(self):
        text = "[action]waves silently[/action]"
        segments = parse_speech_segments(text)
        assert segments == []

    def test_markdown_stripped_in_segments(self):
        text = "**Hello** world! [action]smiles[/action] *Great* to meet you."
        segments = parse_speech_segments(text)
        assert segments == [
            ("Hello world!", None),
            ("Great to meet you.", "smiles"),
        ]

    def test_empty_string(self):
        assert parse_speech_segments("") == []

    def test_consecutive_actions_merged_as_pending(self):
        # Two back-to-back actions: the second overwrites pending_action
        text = "[action]stands[/action][action]walks[/action] Hello."
        segments = parse_speech_segments(text)
        # Only the second action ends up as the preceding action for "Hello."
        assert segments == [("Hello.", "walks")]
