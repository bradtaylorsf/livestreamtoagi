"""Eval run endpoints.

Provides eval execution, listing, comparison, export, analysis,
and issue generation from eval results.
"""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.admin.dependencies import get_db, get_llm
from core.models import (
    EvalComparisonResponse,
    EvalExportResponse,
    EvalHistoryPoint,
    EvalRun,
    EvalRunDetail,
    EvalRunRequest,
    EvalRunResponse,
)

if TYPE_CHECKING:
    from core.database import Database
    from core.llm_client import OpenRouterClient

logger = logging.getLogger(__name__)

# Track background eval tasks so shutdown can wait for them
_background_tasks: set[asyncio.Task] = set()

router = APIRouter(tags=["evals"])


@router.get("/simulations/{sim_id}/evals", response_model=list[EvalRunDetail])
async def get_simulation_evals(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[EvalRunDetail]:
    """All eval runs for this simulation with nested results."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    runs = await eval_repo.get_eval_runs(sim_id)
    result = []
    for run in runs:
        results = await eval_repo.get_eval_results(run.id)
        result.append(
            EvalRunDetail(
                **run.model_dump(),
                results=results,
            )
        )
    return result


@router.post("/simulations/{sim_id}/evals/run", response_model=EvalRunResponse)
async def run_simulation_evals(
    sim_id: uuid_mod.UUID,
    body: EvalRunRequest,
    db: Database = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm),
) -> EvalRunResponse:
    """Trigger eval run -- dispatches asynchronously and returns immediately."""
    from core.eval.engine import EvalEngine
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)

    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)
    sim = await sim_repo.get(sim_id)
    model_versions = sim.model_versions if sim else {}

    eval_run = await eval_repo.create_eval_run(
        sim_id,
        body.eval_suite or "full",
        model_versions=model_versions,
    )
    run_id = eval_run.id

    async def _run_eval_background() -> None:
        try:
            await engine.run(
                sim_id,
                categories=body.categories,
                suite=body.eval_suite,
                existing_run_id=run_id,
            )
        except Exception:
            logger.exception("Background eval run %s failed", run_id)
            try:
                await eval_repo.update_eval_run(run_id, status="failed")
            except Exception:
                logger.exception("Failed to mark eval run %s as failed", run_id)

    task = asyncio.create_task(_run_eval_background())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return EvalRunResponse(
        eval_run_id=str(run_id),
        status="running",
    )


@router.get("/evals", response_model=list[EvalRun])
async def list_eval_runs(
    limit: int = 50,
    offset: int = 0,
    db: Database = Depends(get_db),
) -> list[EvalRun]:
    """Paginated list of all eval runs across simulations."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    return await eval_repo.get_all_eval_runs(limit=limit, offset=offset)


@router.get("/evals/categories")
async def eval_categories(
    db: Database = Depends(get_db),
) -> list[str]:
    """Distinct eval categories from all results."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    return await eval_repo.get_eval_categories()


@router.get("/evals/compare", response_model=EvalComparisonResponse)
async def compare_evals(
    run_a: str,
    run_b: str,
    db: Database = Depends(get_db),
) -> EvalComparisonResponse:
    """Side-by-side comparison of two eval runs."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    try:
        a_id = uuid_mod.UUID(run_a)
        b_id = uuid_mod.UUID(run_b)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid UUID format for run_a or run_b",
        ) from exc

    run_a_obj = await eval_repo.get_eval_run(a_id)
    run_b_obj = await eval_repo.get_eval_run(b_id)
    if run_a_obj is None or run_b_obj is None:
        raise HTTPException(status_code=404, detail="One or both eval runs not found")

    results_a = await eval_repo.get_eval_results(a_id)
    results_b = await eval_repo.get_eval_results(b_id)

    return EvalComparisonResponse(
        run_a=EvalRunDetail(**run_a_obj.model_dump(), results=results_a),
        run_b=EvalRunDetail(**run_b_obj.model_dump(), results=results_b),
    )


@router.get("/evals/history", response_model=list[EvalHistoryPoint])
async def eval_history(
    category: str,
    db: Database = Depends(get_db),
) -> list[EvalHistoryPoint]:
    """Score history for a category across all runs, for charting."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    rows = await eval_repo.get_eval_history(category)
    return [EvalHistoryPoint(**r) for r in rows]


@router.get("/evals/{eval_id}", response_model=EvalRunDetail)
async def get_eval_result(
    eval_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> EvalRunDetail:
    """Full eval run with all results."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    run = await eval_repo.get_eval_run(eval_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    results = await eval_repo.get_eval_results(run.id)
    return EvalRunDetail(**run.model_dump(), results=results)


@router.post("/evals/{eval_id}/create-issues")
async def create_issues_from_eval(
    eval_id: uuid_mod.UUID,
    threshold: int = Query(default=60),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Generate GitHub issues from low-scoring eval categories."""
    from core.eval.issue_generator import EvalIssueGenerator
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    generator = EvalIssueGenerator(
        db=db,
        eval_repo=eval_repo,
        eval_run_id=eval_id,
        score_threshold=threshold,
    )
    return await generator.generate_and_create()


@router.get("/evals/{eval_id}/export", response_model=EvalExportResponse)
async def export_eval(
    eval_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> EvalExportResponse:
    """Export full eval results as JSON."""
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    run = await eval_repo.get_eval_run(eval_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    results = await eval_repo.get_eval_results(run.id)
    return EvalExportResponse(eval_run=run, results=results)


@router.post("/evals/{eval_id}/analyze")
async def analyze_eval(
    eval_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm),
) -> dict[str, Any]:
    """Run eval analyzer on a completed eval run."""
    from core.eval.analyzer import EvalAnalyzer
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    analyzer = EvalAnalyzer(db=db, eval_repo=eval_repo, llm_client=llm)
    try:
        result = await analyzer.analyze(eval_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


@router.get("/evals/{eval_id}/analysis")
async def get_eval_analysis(
    eval_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm),
) -> dict[str, Any]:
    """Get stored analysis for an eval run."""
    from core.eval.analyzer import EvalAnalyzer
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    analyzer = EvalAnalyzer(db=db, eval_repo=eval_repo, llm_client=llm)
    result = await analyzer.get_analysis(eval_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No analysis found for this eval run")
    return result.model_dump()
