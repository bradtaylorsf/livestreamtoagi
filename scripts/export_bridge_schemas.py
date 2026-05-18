#!/usr/bin/env python3
"""Regenerate the committed Node-side bridge JSON Schema (issue #541, E4-2).

The Pydantic models in ``core/bridge/contract.py`` are the single source of
truth. This script serialises :func:`core.bridge.contract.export_json_schema`
to ``core/bridge/schemas/bridge-protocol.schema.json`` so the Node side has a
committed artifact to validate against.

Output is deterministic — sorted keys, two-space indent, trailing newline — so
the contract test can assert the committed file equals a fresh export and catch
any drift between the models and the checked-in schema.

Usage::

    .venv/bin/python scripts/export_bridge_schemas.py        # write the file
    .venv/bin/python scripts/export_bridge_schemas.py --check # verify, no write

This is pure schema serialisation: no network, no Node, no LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a plain script (`python scripts/export_bridge_schemas.py`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.bridge.contract import export_json_schema  # noqa: E402

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "bridge"
    / "schemas"
    / "bridge-protocol.schema.json"
)


def render() -> str:
    """Deterministic JSON text for the current contract."""
    return json.dumps(export_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed schema is stale instead of writing it.",
    )
    args = parser.parse_args()

    rendered = render()

    if args.check:
        if not SCHEMA_PATH.is_file():
            print(f"missing committed schema: {SCHEMA_PATH}", file=sys.stderr)
            return 1
        current = SCHEMA_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "committed bridge schema is stale — run "
                "`.venv/bin/python scripts/export_bridge_schemas.py`",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {SCHEMA_PATH} is up to date")
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
