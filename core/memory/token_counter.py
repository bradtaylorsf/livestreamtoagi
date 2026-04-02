"""Token counting using tiktoken (cl100k_base encoding)."""

from __future__ import annotations

import tiktoken


class TokenCounter:
    """Counts tokens using OpenAI's cl100k_base encoding (used by Claude/GPT-4)."""

    def __init__(self) -> None:
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Return the number of tokens in the given text."""
        return len(self._encoding.encode(text))
