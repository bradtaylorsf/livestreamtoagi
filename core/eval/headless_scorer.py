"""Headless eval scorer (issue #859).

Scores a headless sim folder against the 12 dashboard eval categories using a
mix of deterministic signal extractors (over the decision log) and LLM-judge
calls that reuse the existing rubric prompts under ``evals/prompts/``.

LLM-judge calls are cached on disk by ``(decision_log_hash, category)`` so
re-scoring a sim costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.eval.headless_signals import (
    DETERMINISTIC_SIGNALS,
    SIM_FOLDER_AWARE_SIGNALS,
    collect_tool_intents,
    collect_utterances,
    collect_world_events,
)
from core.eval.prompt_loader import load_prompt
from core.simulation.decision_log_schema import DecisionLogRow, UtteranceRow
from core.simulation.decision_logger import DecisionLogReader

logger = logging.getLogger(__name__)

OUTPUT_SCHEMA_VERSION = 1
SCORER_NAME = "headless"

# Dashboard categories — the 12 originals plus build_quality (#876).
ALL_CATEGORIES: tuple[str, ...] = (
    "creativity",
    "agency",
    "productivity",
    "social_dynamics",
    "economic_behavior",
    "internal_state",
    "entertainment",
    "safety",
    "errors",
    "dialogue_quality",
    "simulation_narrative",
    "world_evolution",
    "build_quality",
    "ownership",
)

LLM_JUDGE_CATEGORIES: tuple[str, ...] = (
    "dialogue_quality",
    "entertainment",
    "simulation_narrative",
    "creativity",
)

EVAL_SCORES_FILENAME = "eval_scores.json"
EVAL_CACHE_DIRNAME = ".eval_cache"


def compute_decision_log_hash(decision_log_path: Path) -> str:
    """SHA-256 of the decision log file bytes; stable across runs."""
    sha = hashlib.sha256()
    with decision_log_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _load_scenario_eval_targets(sim_folder: Path) -> dict[str, Any]:
    """Best-effort: read metadata.json → scenario YAML → eval_targets block."""
    meta_path = sim_folder / "metadata.json"
    if not meta_path.is_file():
        return {}
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("headless_scorer: cannot read metadata.json: %s", exc)
        return {}
    scenario_path_str = meta.get("scenario")
    if not scenario_path_str:
        return {}
    scenario_path = Path(scenario_path_str)
    if not scenario_path.is_file():
        return {}
    try:
        parsed = yaml.safe_load(scenario_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("headless_scorer: cannot parse scenario %s: %s", scenario_path, exc)
        return {}
    targets = parsed.get("eval_targets")
    return targets if isinstance(targets, dict) else {}


def _render_decision_log_excerpt(rows: list[DecisionLogRow]) -> str:
    """Compact text view of the decision log for LLM-judge prompts.

    Stays under a hard char budget; the existing rubric prompts already
    truncate aggressively but we don't want to push a multi-MB log either.
    """
    parts: list[str] = []
    utterances = collect_utterances(rows)
    intents = collect_tool_intents(rows)
    world_events = collect_world_events(rows)

    parts.append("### Utterances")
    if utterances:
        for u in utterances[:200]:
            text = (u.payload.text or "").strip().replace("\n", " ")
            text = text[:280]
            parts.append(f"- t={u.tick} {u.actor_id}({u.payload.channel or 'chat'}): {text}")
    else:
        parts.append("(no utterances)")

    parts.append("\n### Tool Intents")
    if intents:
        for i in intents[:200]:
            args_view = ", ".join(f"{k}={v}" for k, v in (i.payload.args or {}).items())[:200]
            parts.append(
                f"- t={i.tick} {i.actor_id} {i.payload.tool_name}({args_view}) "
                f"status={i.payload.status} "
                f"block_reason={i.payload.block_reason or '-'}"
            )
    else:
        parts.append("(no tool intents)")

    parts.append("\n### World Events")
    if world_events:
        for w in world_events[:80]:
            parts.append(
                f"- t={w.tick} event={w.payload.event_type} "
                f"trigger={w.payload.trigger or '-'} "
                f"severity={w.payload.severity or '-'}"
            )
    else:
        parts.append("(no world events)")

    return "\n".join(parts)


def _render_llm_user_prompt(
    prompt_config: dict[str, Any],
    rows: list[DecisionLogRow],
) -> str:
    """Format an LLM-judge user prompt around a decision-log excerpt."""
    rubric = prompt_config.get("rubric", {})
    sub_scores = prompt_config.get("sub_scores", []) or []
    output_schema = prompt_config.get("output_schema", {})

    parts: list[str] = ["## Scoring Rubric"]
    for score_range, desc in rubric.items():
        parts.append(f"- **{score_range}**: {desc}")
    parts.append("\n## Sub-scores to evaluate")
    for sub in sub_scores:
        if isinstance(sub, dict):
            for name, desc in sub.items():
                parts.append(f"- **{name}**: {desc}")
        else:
            parts.append(f"- {sub}")
    parts.append("\n## Required output format")
    parts.append("Respond with valid JSON matching this schema:")
    parts.append(f"```json\n{json.dumps(output_schema, indent=2)}\n```")
    parts.append("\n## Decision Log Excerpt")
    parts.append(_render_decision_log_excerpt(rows)[:80_000])
    return "\n".join(parts)


def _parse_llm_json(content: str) -> dict[str, Any]:
    """Extract JSON from an LLM response, tolerating code fences."""
    text = (content or "").strip()
    if "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {"score": 0, "reasoning": text[:500]}


class HeadlessScorer:
    """Scores a headless sim folder against the 12 dashboard eval categories.

    LLM-judge categories use ``llm_client``; deterministic categories run
    without one. Pass a stub for tests. Results are cached at
    ``<sim_folder>/.eval_cache/<hash>-<category>.json``.
    """

    def __init__(
        self,
        sim_folder: str | Path,
        *,
        llm_client: Any | None = None,
        cache_dir: Path | None = None,
        categories: Iterable[str] | None = None,
        model: str | None = None,
    ) -> None:
        self._sim_folder = Path(sim_folder)
        self._llm = llm_client
        self._cache_dir = cache_dir or (self._sim_folder / EVAL_CACHE_DIRNAME)
        self._categories = tuple(categories) if categories else ALL_CATEGORIES
        self._model = model

    @property
    def sim_folder(self) -> Path:
        return self._sim_folder

    async def score(self) -> dict[str, Any]:
        """Compute scores for all configured categories and write eval_scores.json."""
        reader = DecisionLogReader(self._sim_folder)
        rows: list[DecisionLogRow] = list(reader.replay())
        log_hash = compute_decision_log_hash(reader.path)

        eval_targets = _load_scenario_eval_targets(self._sim_folder)

        categories_out: dict[str, dict[str, Any]] = {}
        for cat in self._categories:
            if cat in DETERMINISTIC_SIGNALS:
                if cat in SIM_FOLDER_AWARE_SIGNALS:
                    signal = DETERMINISTIC_SIGNALS[cat](rows, sim_folder=self._sim_folder)
                else:
                    signal = DETERMINISTIC_SIGNALS[cat](rows)
                categories_out[cat] = {
                    **signal,
                    "signal_type": "deterministic",
                }
            elif cat in LLM_JUDGE_CATEGORIES:
                categories_out[cat] = await self._score_llm_judge(cat, rows, log_hash=log_hash)
            else:
                # Unknown category — emit a neutral placeholder rather than crash.
                categories_out[cat] = {
                    "score": 0.0,
                    "reasoning": "no scorer registered for category",
                    "evidence": [],
                    "sub_scores": {},
                    "confidence": 0.0,
                    "signal_type": "unsupported",
                }

        success_criteria_results = await self._evaluate_success_criteria(
            eval_targets, rows, log_hash=log_hash
        )

        metadata_path = self._sim_folder / "metadata.json"
        scenario_id: str | None = None
        if metadata_path.is_file():
            try:
                meta = json.loads(metadata_path.read_text())
                scenario_id = meta.get("scenario_id")
            except (OSError, json.JSONDecodeError):
                pass

        result: dict[str, Any] = {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "scorer": SCORER_NAME,
            "scored_at": datetime.now(UTC).isoformat(),
            "decision_log_hash": log_hash,
            "scenario_id": scenario_id,
            "categories": categories_out,
            "success_criteria": success_criteria_results,
            "primary": list(eval_targets.get("primary", []))
            if isinstance(eval_targets.get("primary"), list)
            else [],
            "secondary": list(eval_targets.get("secondary", []))
            if isinstance(eval_targets.get("secondary"), list)
            else [],
        }

        output_path = self._sim_folder / EVAL_SCORES_FILENAME
        output_path.write_text(json.dumps(result, indent=2, default=str))
        return result

    # ─── LLM-judge ────────────────────────────────────────────────────

    async def _score_llm_judge(
        self,
        category: str,
        rows: list[DecisionLogRow],
        *,
        log_hash: str,
    ) -> dict[str, Any]:
        cached = self._read_cache(log_hash, category)
        if cached is not None:
            cached["cached"] = True
            cached["signal_type"] = "llm_judge"
            return cached

        prompt_config = load_prompt(category)
        system_prompt = prompt_config.get("system") or ""
        user_prompt = _render_llm_user_prompt(prompt_config, rows)
        result: dict[str, Any]
        if self._llm is None:
            result = {
                "score": 0.0,
                "reasoning": "no llm_client available; skipped",
                "evidence": {},
                "sub_scores": {},
                "confidence": 0.0,
                "signal_type": "llm_judge",
                "skipped": True,
            }
        else:
            model = self._model or prompt_config.get("model") or "claude-haiku-4-5"
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                agent_id="headless_scorer",
                temperature=prompt_config.get("temperature", 0.3),
                max_tokens=prompt_config.get("max_tokens", 2048),
                timeout=120.0,
            )
            parsed = _parse_llm_json(getattr(response, "content", "") or "")
            score_value = parsed.get("score", 0)
            try:
                score_float = float(score_value)
            except (TypeError, ValueError):
                score_float = 0.0
            result = {
                "score": score_float,
                "reasoning": parsed.get("reasoning", ""),
                "evidence": parsed.get("evidence") or {},
                "sub_scores": parsed.get("sub_scores") or {},
                "confidence": parsed.get("confidence", 0.7),
                "signal_type": "llm_judge",
                "model": model,
                "runtime_model": getattr(response, "runtime_model", None),
            }
        self._write_cache(log_hash, category, result)
        return result

    # ─── Success criteria ─────────────────────────────────────────────

    async def _evaluate_success_criteria(
        self,
        eval_targets: dict[str, Any],
        rows: list[DecisionLogRow],
        *,
        log_hash: str,
    ) -> list[dict[str, Any]]:
        criteria = eval_targets.get("success_criteria") if eval_targets else None
        if not isinstance(criteria, dict) or not criteria:
            return []

        out: list[dict[str, Any]] = []
        for category, criterion in criteria.items():
            cache_key = f"success-{category}"
            cached = self._read_cache(log_hash, cache_key)
            if cached is not None:
                cached["cached"] = True
                out.append(cached)
                continue

            entry = await self._judge_single_criterion(category, str(criterion), rows)
            self._write_cache(log_hash, cache_key, entry)
            out.append(entry)
        return out

    async def _judge_single_criterion(
        self,
        category: str,
        criterion: str,
        rows: list[DecisionLogRow],
    ) -> dict[str, Any]:
        if self._llm is None:
            return {
                "category": category,
                "criterion": criterion,
                "pass": False,
                "reason": "no llm_client available; success criterion skipped",
                "skipped": True,
            }
        system = (
            "You evaluate whether a simulation meets a single declared success "
            'criterion. Respond with strict JSON: {"pass": bool, "reason": str}.'
        )
        user = (
            f"## Category\n{category}\n\n"
            f"## Criterion\n{criterion}\n\n"
            "## Decision Log Excerpt\n"
            f"{_render_decision_log_excerpt(rows)[:60_000]}"
        )
        model = self._model or "claude-haiku-4-5"
        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            agent_id="headless_scorer",
            temperature=0.2,
            max_tokens=512,
            timeout=60.0,
        )
        parsed = _parse_llm_json(getattr(response, "content", "") or "")
        return {
            "category": category,
            "criterion": criterion,
            "pass": bool(parsed.get("pass", False)),
            "reason": parsed.get("reason", ""),
            "model": model,
            "runtime_model": getattr(response, "runtime_model", None),
        }

    # ─── Cache helpers ────────────────────────────────────────────────

    def _cache_path(self, log_hash: str, key: str) -> Path:
        return self._cache_dir / f"{log_hash}-{key}.json"

    def _read_cache(self, log_hash: str, key: str) -> dict[str, Any] | None:
        path = self._cache_path(log_hash, key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("headless_scorer: cache read failed %s: %s", path, exc)
            return None

    def _write_cache(self, log_hash: str, key: str, payload: dict[str, Any]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._cache_path(log_hash, key).write_text(json.dumps(payload, indent=2, default=str))
        except OSError as exc:
            logger.warning("headless_scorer: cache write failed for %s: %s", key, exc)


def _utterances_text(rows: Iterable[DecisionLogRow], limit: int = 200) -> str:
    """Compact utterance dump — used by tests and callers wanting a quick text view."""
    out: list[str] = []
    for r in rows:
        if isinstance(r, UtteranceRow):
            text = (r.payload.text or "").strip().replace("\n", " ")[:280]
            out.append(f"t={r.tick} {r.actor_id}: {text}")
            if len(out) >= limit:
                break
    return "\n".join(out)


__all__ = [
    "ALL_CATEGORIES",
    "EVAL_SCORES_FILENAME",
    "HeadlessScorer",
    "LLM_JUDGE_CATEGORIES",
    "OUTPUT_SCHEMA_VERSION",
    "SCORER_NAME",
    "compute_decision_log_hash",
]
