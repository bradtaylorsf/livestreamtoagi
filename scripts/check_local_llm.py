#!/usr/bin/env python3
"""Check a local OpenAI-compatible LLM server before running simulations.

Usage:
    pnpm llm:local --list-only
    .venv/bin/python scripts/check_local_llm.py --list-only
    LLM_PROVIDER=lmstudio LOCAL_LLM_MODEL=qwen3 .venv/bin/python scripts/check_local_llm.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def _run(args: argparse.Namespace) -> int:
    base_url = args.base_url or os.environ.get(
        "LOCAL_LLM_BASE_URL",
        os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1"),
    )
    api_key = args.api_key or os.environ.get("LOCAL_LLM_API_KEY", "lm-studio")
    model = args.model or os.environ.get("LOCAL_LLM_MODEL", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=args.timeout,
    ) as client:
        try:
            models_resp = await client.get("/models")
            models_resp.raise_for_status()
        except Exception as exc:
            print(f"FAIL: could not reach {base_url.rstrip('/')}/models")
            print(f"      {exc}")
            return 1

        models_data = models_resp.json()
        model_ids = [
            str(item.get("id"))
            for item in models_data.get("data", [])
            if item.get("id")
        ]
        print(f"OK: connected to {base_url.rstrip('/')}")
        if model_ids:
            print("Models:")
            for model_id in model_ids:
                selected = "  *" if model_id == model else "   "
                print(f"{selected} {model_id}")
        else:
            print("WARN: /models returned no model IDs")

        if args.list_only:
            return 0

        if not model:
            if not model_ids:
                print("FAIL: set LOCAL_LLM_MODEL or load a model in LM Studio")
                return 1
            model = model_ids[0]
            print(f"Using first model for smoke test: {model}")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a concise test assistant."},
                {"role": "user", "content": args.prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 40,
        }
        try:
            chat_resp = await client.post("/chat/completions", json=payload)
            chat_resp.raise_for_status()
        except Exception as exc:
            print(f"FAIL: chat completion failed for model {model!r}")
            print(f"      {exc}")
            return 1

        data = chat_resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            print("FAIL: chat completion returned no content")
            return 1

        usage = data.get("usage") or {}
        print("OK: chat completion returned content")
        print(f"Response: {content.strip()[:200]}")
        if usage:
            print(
                "Usage: "
                f"prompt={usage.get('prompt_tokens', 0)} "
                f"completion={usage.get('completion_tokens', 0)}"
            )
        else:
            print("Usage: not reported by provider")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check local OpenAI-compatible LLM server")
    parser.add_argument("--base-url", default=None, help="Base URL, e.g. http://localhost:1234/v1")
    parser.add_argument("--api-key", default=None, help="API key, if the local server requires one")
    parser.add_argument("--model", default=None, help="Model ID to test")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds")
    parser.add_argument("--list-only", action="store_true", help="Only list /models")
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: local llm ready",
        help="Prompt for the chat smoke test",
    )
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
