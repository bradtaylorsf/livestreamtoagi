"""Generate GitHub issues from eval findings.

Reads eval results for a given eval run, identifies low-scoring categories,
checks for duplicate issues, and creates GitHub issues via the `gh` CLI.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.database import Database
    from core.repos.eval_repo import EvalRepo

logger = logging.getLogger(__name__)

DEFAULT_SCORE_THRESHOLD = 60


class EvalIssueGenerator:
    """Create GitHub issues from low-scoring eval categories."""

    def __init__(
        self,
        *,
        db: Database,
        eval_repo: EvalRepo,
        eval_run_id: uuid.UUID,
        score_threshold: int = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self._db = db
        self._eval_repo = eval_repo
        self._eval_run_id = eval_run_id
        self._score_threshold = score_threshold

    async def generate_and_create(self) -> list[dict[str, Any]]:
        """Load eval results, generate issues for low scores, create via gh CLI.

        Returns list of dicts with keys: category, title, url, status ('created'|'skipped'|'error').
        """
        run = await self._eval_repo.get_eval_run(self._eval_run_id)
        if run is None:
            return [{"category": "N/A", "title": "N/A", "url": None, "status": "error",
                     "reason": f"Eval run {self._eval_run_id} not found"}]

        results = await self._eval_repo.get_eval_results(self._eval_run_id)
        if not results:
            return []

        issues: list[dict[str, Any]] = []
        for result in results:
            score = float(result.score) if result.score is not None else 100
            if score >= self._score_threshold:
                continue

            category = result.category
            title = f"{category}: scored {int(score)}/100 (eval {str(self._eval_run_id)[:8]})"

            # Check for duplicates
            if self._check_duplicate(category):
                issues.append({
                    "category": category,
                    "title": title,
                    "url": None,
                    "status": "skipped",
                    "reason": "Duplicate issue exists",
                })
                continue

            # Build issue body
            body = self._build_issue_body(result, run)

            # Create via gh CLI
            url = self._create_github_issue(title, body)
            if url:
                issues.append({
                    "category": category,
                    "title": title,
                    "url": url,
                    "status": "created",
                })
            else:
                issues.append({
                    "category": category,
                    "title": title,
                    "url": None,
                    "status": "error",
                    "reason": "gh issue create failed",
                })

        return issues

    def _check_duplicate(self, category: str) -> bool:
        """Check if an open issue already exists for this category."""
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--label", "eval-finding",
                    "--search", category,
                    "--state", "open",
                    "--json", "number,title",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                existing = json.loads(result.stdout)
                # Check if any existing issue title contains this category
                for issue in existing:
                    if category.lower() in issue.get("title", "").lower():
                        return True
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            logger.warning("Failed to check for duplicate issues", exc_info=True)
        return False

    def _build_issue_body(self, result: Any, run: Any) -> str:
        """Build the GitHub issue body from eval result data."""
        lines = [
            f"## Eval Finding: {result.category}",
            "",
            f"**Score:** {int(float(result.score))}/100",
            f"**Eval Run:** `{self._eval_run_id}`",
            f"**Simulation:** `{run.simulation_id}`",
            f"**Suite:** {run.eval_suite}",
            "",
        ]

        if result.reasoning:
            lines.extend(["### Reasoning", "", result.reasoning, ""])

        if result.evidence:
            lines.extend(["### Evidence", ""])
            evidence = result.evidence if isinstance(result.evidence, dict) else {}
            for key, value in evidence.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")

        if result.sub_scores:
            lines.extend(["### Sub-scores", ""])
            sub_scores = result.sub_scores if isinstance(result.sub_scores, dict) else {}
            for key, value in sub_scores.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        lines.extend([
            "---",
            f"*Auto-generated from eval run `{str(self._eval_run_id)[:8]}`*",
        ])
        return "\n".join(lines)

    def _create_github_issue(self, title: str, body: str) -> str | None:
        """Create a GitHub issue via gh CLI. Returns the issue URL or None."""
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "create",
                    "--title", title,
                    "--body", body,
                    "--label", "eval-finding",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                return url
            logger.error("gh issue create failed: %s", result.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.error("Failed to create GitHub issue", exc_info=True)
        return None
