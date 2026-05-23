#!/usr/bin/env python3
"""Entrypoint for the text-only Minecraft command eval CLI."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.minecraft.eval.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
