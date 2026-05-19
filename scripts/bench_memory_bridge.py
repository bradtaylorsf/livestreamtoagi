#!/usr/bin/env python3
"""Benchmark memory bridge handler overhead against direct memory calls.

The default benchmark is offline and deterministic. It uses in-memory fakes for
the same manager methods the bridge handler delegates to, so no database, LLM,
or embedding provider is needed. Optional ``--pgvector`` mode seeds a temporary
simulation namespace in PostgreSQL and measures real recall search latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# This benchmark must never require paid embeddings.
os.environ["EMBEDDING_PROVIDER"] = "deterministic"

from core.bridge.contract import PROTOCOL_VERSION, BridgeRequest, CostContext  # noqa: E402
from core.bridge.handlers.memory import handle_memory_read, handle_memory_write  # noqa: E402
from core.memory.compaction import CompactionResult  # noqa: E402
from core.memory.embeddings import generate_deterministic_embedding  # noqa: E402
from core.models import RecallMemory, RecallMemoryCreate, Transcript  # noqa: E402

DEFAULT_ITERATIONS = 2000
DEFAULT_WARMUP = 200
DEFAULT_PGVECTOR_ITERATIONS = 200
DEFAULT_PGVECTOR_WARMUP = 25
DEFAULT_PGVECTOR_SEED_COUNT = 250

SIMULATION_ID = "11111111-1111-1111-1111-111111111111"
SIMULATION_UUID = uuid.UUID(SIMULATION_ID)
AGENT_ID = "vera"
RUN_ID = "memory-bridge-perf"
QUERY = "what did rex build near spawn"

# Documented budgets. Keep docs/minecraft/memory-bridge-performance.md in sync
# by running this script with --write-report after changing them.
BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS = 2.0
OFFLINE_BRIDGE_P95_BUDGET_MS = {
    "core_read": 5.0,
    "recall_read": 5.0,
    "write_append": 5.0,
}
PGVECTOR_RECALL_P95_BUDGET_MS = 75.0
PGVECTOR_RECALL_MAX_ADVISORY_MS = 250.0

REPORT_START = "<!-- benchmark-results:start -->"
REPORT_END = "<!-- benchmark-results:end -->"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "docs" / "minecraft" / "memory-bridge-performance.md"


@dataclass
class FakeCoreMemoryManager:
    value: str = "## My Core Memory\n\n### Who I am\nVera keeps the bridge honest."

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        if agent_id != AGENT_ID:
            raise ValueError(f"unexpected agent_id {agent_id!r}")
        if simulation_id != SIMULATION_UUID:
            raise ValueError(f"unexpected simulation_id {simulation_id!r}")
        return self.value


@dataclass
class FakeRecallMemoryManager:
    value: str = "## Relevant memories\n- [event] Rex built a spawn bridge."

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        if agent_id != AGENT_ID:
            raise ValueError(f"unexpected agent_id {agent_id!r}")
        if not query_text:
            raise ValueError("query_text is required")
        if limit != 5:
            raise ValueError(f"unexpected limit {limit!r}")
        if simulation_id != SIMULATION_UUID:
            raise ValueError(f"unexpected simulation_id {simulation_id!r}")
        return self.value


class FakeMemoryCompactor:
    def __init__(self) -> None:
        self.result = CompactionResult(
            transcript=Transcript(
                id=1,
                event_type="event",
                participants=["vera", "rex"],
                content="Rex finished the spawn bridge and Vera logged the handoff.",
                token_count=9,
            ),
            recall_memory=RecallMemory(
                id=1,
                agent_id=AGENT_ID,
                summary="Vera logged Rex finishing the spawn bridge handoff.",
                embedding=[0.125, 0.25, 0.5],
                event_type="event",
                participants=["vera", "rex"],
                transcript_id=1,
            ),
        )

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
    ) -> CompactionResult | None:
        if agent_id != AGENT_ID:
            raise ValueError(f"unexpected agent_id {agent_id!r}")
        if not interaction or not interaction.strip():
            return None
        if event_type != "event":
            raise ValueError(f"unexpected event_type {event_type!r}")
        if participants != ["vera", "rex"]:
            raise ValueError(f"unexpected participants {participants!r}")
        if conversation_id != "conversation-memory-bridge-perf":
            raise ValueError(f"unexpected conversation_id {conversation_id!r}")
        return self.result


@dataclass
class FakeMemoryServices:
    core_memory: Any
    recall_memory: Any
    compactor: Any
    memory_backend: Any | None = None

    def __post_init__(self) -> None:
        if self.memory_backend is None:
            self.memory_backend = self.recall_memory


@dataclass(frozen=True)
class OperationSpec:
    name: str
    direct: Callable[[], Awaitable[Any]]
    bridge: Callable[[], Awaitable[Any]]


def build_fake_services() -> FakeMemoryServices:
    """Build deterministic in-memory services matching the bridge handler surface."""
    recall = FakeRecallMemoryManager()
    return FakeMemoryServices(
        core_memory=FakeCoreMemoryManager(),
        recall_memory=recall,
        memory_backend=recall,
        compactor=FakeMemoryCompactor(),
    )


def memory_read_request(*, tier: str) -> BridgeRequest:
    return BridgeRequest(
        version=PROTOCOL_VERSION,
        request_id=f"req-memory-{tier}-perf",
        agent_id=AGENT_ID,
        run_id=RUN_ID,
        simulation_id=SIMULATION_ID,
        service="memory",
        method="recall",
        payload={"query": QUERY, "tier": tier, "limit": 5},
        deadline_ms=5000,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="memory-bridge-perf",
            estimated_cost_usd=0.0,
        ),
    )


def memory_write_request() -> BridgeRequest:
    return BridgeRequest(
        version=PROTOCOL_VERSION,
        request_id="req-memory-write-perf",
        agent_id=AGENT_ID,
        run_id=RUN_ID,
        simulation_id=SIMULATION_ID,
        service="memory",
        method="write",
        payload={
            "content": "Rex finished the spawn bridge and Vera logged the handoff.",
            "kind": "event",
            "metadata": {
                "participants": ["vera", "rex"],
                "conversation_id": "conversation-memory-bridge-perf",
            },
        },
        deadline_ms=5000,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="memory-bridge-perf",
            estimated_cost_usd=0.0,
        ),
    )


async def collect_parity_results() -> dict[str, dict[str, Any]]:
    """Return direct and bridge outputs for the offline fake operations."""
    services = build_fake_services()
    core_request = memory_read_request(tier="core")
    recall_request = memory_read_request(tier="recall")
    write_request = memory_write_request()

    direct_core = await services.core_memory.get_core_memory(
        AGENT_ID,
        simulation_id=SIMULATION_UUID,
    )
    bridge_core = await handle_memory_read(core_request, services)

    direct_recall = await services.memory_backend.retrieve_recall_memories(
        AGENT_ID,
        QUERY,
        limit=5,
        simulation_id=SIMULATION_UUID,
    )
    bridge_recall = await handle_memory_read(recall_request, services)

    direct_write = await services.compactor.compact_interaction(
        agent_id=AGENT_ID,
        interaction=write_request.payload["content"],
        event_type=write_request.payload["kind"],
        participants=write_request.payload["metadata"]["participants"],
        conversation_id=write_request.payload["metadata"]["conversation_id"],
    )
    bridge_write = await handle_memory_write(write_request, services)

    if direct_write is None:
        raise RuntimeError("fake write returned no memory")

    return {
        "core_read": {
            "direct": direct_core,
            "bridge": bridge_core["core_memory"],
        },
        "recall_read": {
            "direct": direct_recall,
            "bridge": bridge_recall["formatted"],
        },
        "write_append": {
            "direct": str(direct_write.recall_memory.id),
            "bridge": bridge_write["memory_id"],
        },
    }


def _offline_operation_specs(services: FakeMemoryServices) -> list[OperationSpec]:
    core_request = memory_read_request(tier="core")
    recall_request = memory_read_request(tier="recall")
    write_request = memory_write_request()

    async def direct_core() -> str:
        return await services.core_memory.get_core_memory(AGENT_ID, simulation_id=SIMULATION_UUID)

    async def bridge_core() -> dict[str, Any]:
        return await handle_memory_read(core_request, services)

    async def direct_recall() -> str:
        return await services.memory_backend.retrieve_recall_memories(
            AGENT_ID,
            QUERY,
            limit=5,
            simulation_id=SIMULATION_UUID,
        )

    async def bridge_recall() -> dict[str, Any]:
        return await handle_memory_read(recall_request, services)

    async def direct_write() -> CompactionResult | None:
        return await services.compactor.compact_interaction(
            agent_id=AGENT_ID,
            interaction=write_request.payload["content"],
            event_type=write_request.payload["kind"],
            participants=write_request.payload["metadata"]["participants"],
            conversation_id=write_request.payload["metadata"]["conversation_id"],
        )

    async def bridge_write() -> dict[str, Any]:
        return await handle_memory_write(write_request, services)

    return [
        OperationSpec("core_read", direct_core, bridge_core),
        OperationSpec("recall_read", direct_recall, bridge_recall),
        OperationSpec("write_append", direct_write, bridge_write),
    ]


async def _measure(
    func: Callable[[], Awaitable[Any]],
    *,
    iterations: int,
    warmup: int,
) -> list[float]:
    samples: list[float] = []
    total = iterations + warmup
    for index in range(total):
        started = time.perf_counter_ns()
        await func()
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        if index >= warmup:
            samples.append(elapsed_ms)
    return samples


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100) * len(ordered)) - 1))
    return ordered[index]


def timing_stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": statistics.fmean(samples),
        "p50": _percentile(samples, 50),
        "p95": _percentile(samples, 95),
        "max": max(samples),
    }


def _overhead_stats(bridge: dict[str, float], direct: dict[str, float]) -> dict[str, float]:
    return {key: bridge[key] - direct[key] for key in ("mean", "p50", "p95", "max")}


async def run_offline_benchmark(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, Any]:
    services = build_fake_services()
    operations: dict[str, Any] = {}

    for spec in _offline_operation_specs(services):
        direct_samples = await _measure(spec.direct, iterations=iterations, warmup=warmup)
        bridge_samples = await _measure(spec.bridge, iterations=iterations, warmup=warmup)
        direct = timing_stats(direct_samples)
        bridge = timing_stats(bridge_samples)
        operations[spec.name] = {
            "direct_ms": direct,
            "bridge_ms": bridge,
            "adapter_overhead_ms": _overhead_stats(bridge, direct),
            "samples": len(direct_samples),
        }

    return {
        "operations": operations,
        "iterations": iterations,
        "warmup": warmup,
    }


async def _deterministic_embedding(text: str) -> list[float]:
    return generate_deterministic_embedding(text)


async def run_pgvector_benchmark(
    *,
    iterations: int = DEFAULT_PGVECTOR_ITERATIONS,
    warmup: int = DEFAULT_PGVECTOR_WARMUP,
    seed_count: int = DEFAULT_PGVECTOR_SEED_COUNT,
) -> dict[str, Any]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {
            "status": "skipped",
            "reason": "DATABASE_URL is not set",
            "iterations": iterations,
            "warmup": warmup,
            "seed_count": seed_count,
        }

    from core.database import Database
    from core.memory.recall_memory import RecallMemoryManager
    from core.repos.memory_repo import MemoryRepo

    simulation_id = uuid.uuid4()
    db = Database(dsn=dsn, min_size=1, max_size=2)
    await db.connect(retries=1, delay=0.1)
    try:
        repo = MemoryRepo(db)
        recall = RecallMemoryManager(repo, embedding_fn=_deterministic_embedding)
        for index in range(seed_count):
            summary = (
                f"Seeded benchmark memory {index}: Rex and Vera inspect bridge "
                f"latency near spawn marker {index % 17}."
            )
            await repo.add_recall(
                RecallMemoryCreate(
                    agent_id=AGENT_ID,
                    summary=summary,
                    embedding=generate_deterministic_embedding(summary),
                    event_type="benchmark",
                    participants=[AGENT_ID, "rex"],
                    transcript_id=None,
                    importance_score=0.5,
                    simulation_id=simulation_id,
                )
            )

        services = FakeMemoryServices(
            core_memory=None,
            recall_memory=recall,
            memory_backend=recall,
            compactor=None,
        )
        request = memory_read_request(tier="recall").model_copy(
            update={"simulation_id": str(simulation_id)}
        )

        async def direct_recall() -> str:
            return await recall.retrieve_recall_memories(
                AGENT_ID,
                QUERY,
                limit=5,
                simulation_id=simulation_id,
            )

        async def bridge_recall() -> dict[str, Any]:
            return await handle_memory_read(request, services)

        direct_samples = await _measure(direct_recall, iterations=iterations, warmup=warmup)
        bridge_samples = await _measure(bridge_recall, iterations=iterations, warmup=warmup)
        direct = timing_stats(direct_samples)
        bridge = timing_stats(bridge_samples)
        return {
            "status": "measured",
            "simulation_id": str(simulation_id),
            "seed_count": seed_count,
            "iterations": iterations,
            "warmup": warmup,
            "direct_ms": direct,
            "bridge_ms": bridge,
            "adapter_overhead_ms": _overhead_stats(bridge, direct),
        }
    finally:
        try:
            await db.execute(
                "DELETE FROM recall_memory WHERE agent_id = $1 AND simulation_id = $2",
                AGENT_ID,
                simulation_id,
            )
        finally:
            await db.disconnect()


def budgets() -> dict[str, Any]:
    return {
        "bridge_adapter_overhead_p95_ms": BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS,
        "offline_bridge_p95_ms": OFFLINE_BRIDGE_P95_BUDGET_MS,
        "pgvector_recall_p95_ms": PGVECTOR_RECALL_P95_BUDGET_MS,
        "pgvector_recall_max_advisory_ms": PGVECTOR_RECALL_MAX_ADVISORY_MS,
    }


def evaluate_budget(summary: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    for name, result in summary["offline"]["operations"].items():
        bridge_p95 = result["bridge_ms"]["p95"]
        bridge_budget = OFFLINE_BRIDGE_P95_BUDGET_MS[name]
        if bridge_p95 > bridge_budget:
            failures.append(f"{name} bridge p95 {bridge_p95:.3f}ms exceeds {bridge_budget:.3f}ms")

        overhead_p95 = result["adapter_overhead_ms"]["p95"]
        if overhead_p95 > BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS:
            failures.append(
                f"{name} adapter p95 overhead {overhead_p95:.3f}ms exceeds "
                f"{BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS:.3f}ms"
            )

    pgvector = summary.get("pgvector")
    if pgvector and pgvector.get("status") == "measured":
        p95 = pgvector["bridge_ms"]["p95"]
        if p95 > PGVECTOR_RECALL_P95_BUDGET_MS:
            failures.append(
                f"pgvector recall bridge p95 {p95:.3f}ms exceeds "
                f"{PGVECTOR_RECALL_P95_BUDGET_MS:.3f}ms"
            )

    return {"within_budget": not failures, "failures": failures}


async def run_benchmark(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
    include_pgvector: bool = False,
    pgvector_iterations: int = DEFAULT_PGVECTOR_ITERATIONS,
    pgvector_warmup: int = DEFAULT_PGVECTOR_WARMUP,
    pgvector_seed_count: int = DEFAULT_PGVECTOR_SEED_COUNT,
) -> dict[str, Any]:
    offline = await run_offline_benchmark(iterations=iterations, warmup=warmup)
    summary: dict[str, Any] = {
        "metadata": {
            "benchmark": "memory_bridge_performance",
            "protocol_version": PROTOCOL_VERSION,
            "embedding_provider": os.environ["EMBEDDING_PROVIDER"],
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "budgets_ms": budgets(),
        "offline": offline,
    }
    if include_pgvector:
        summary["pgvector"] = await run_pgvector_benchmark(
            iterations=pgvector_iterations,
            warmup=pgvector_warmup,
            seed_count=pgvector_seed_count,
        )
    summary["budget"] = evaluate_budget(summary)
    return summary


def _format_ms(value: float) -> str:
    return f"{value:.4f}"


def render_report_results(summary: dict[str, Any]) -> str:
    lines = [
        f"Generated: `{summary['metadata']['generated_at']}`",
        "",
        f"Python: `{summary['metadata']['python']}`",
        f"Platform: `{summary['metadata']['platform']}`",
        f"Embedding provider: `{summary['metadata']['embedding_provider']}`",
        f"Iterations: `{summary['offline']['iterations']}` measured, "
        f"`{summary['offline']['warmup']}` warmup",
        "",
        "| Operation | Direct p50 ms | Direct p95 ms | Bridge p50 ms | "
        "Bridge p95 ms | Adapter p95 ms | Bridge p95 budget ms | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, result in summary["offline"]["operations"].items():
        direct = result["direct_ms"]
        bridge = result["bridge_ms"]
        overhead = result["adapter_overhead_ms"]
        bridge_budget = OFFLINE_BRIDGE_P95_BUDGET_MS[name]
        status = (
            "PASS"
            if bridge["p95"] <= bridge_budget
            and overhead["p95"] <= BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS
            else "FAIL"
        )
        lines.append(
            f"| `{name}` | {_format_ms(direct['p50'])} | {_format_ms(direct['p95'])} | "
            f"{_format_ms(bridge['p50'])} | {_format_ms(bridge['p95'])} | "
            f"{_format_ms(overhead['p95'])} | {_format_ms(bridge_budget)} | {status} |"
        )

    lines.extend(
        [
            "",
            f"Adapter overhead p95 budget: `{BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS:.1f} ms`.",
        ]
    )

    pgvector = summary.get("pgvector")
    if not pgvector:
        lines.extend(
            [
                "",
                "Real pgvector recall: not run in this report. Use "
                "`python scripts/bench_memory_bridge.py --pgvector --check-budget` "
                "with `DATABASE_URL` set to exercise a seeded temporary recall namespace.",
            ]
        )
    elif pgvector.get("status") == "skipped":
        lines.extend(
            [
                "",
                f"Real pgvector recall: skipped ({pgvector['reason']}).",
            ]
        )
    else:
        direct = pgvector["direct_ms"]
        bridge = pgvector["bridge_ms"]
        overhead = pgvector["adapter_overhead_ms"]
        pg_status = "PASS" if bridge["p95"] <= PGVECTOR_RECALL_P95_BUDGET_MS else "FAIL"
        advisory = "PASS" if bridge["max"] <= PGVECTOR_RECALL_MAX_ADVISORY_MS else "ADVISORY FAIL"
        lines.extend(
            [
                "",
                "| Pgvector mode | Direct p50 ms | Direct p95 ms | Bridge p50 ms | "
                "Bridge p95 ms | Adapter p95 ms | P95 budget ms | Max advisory | Status |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
                f"| seeded recall (`{pgvector['seed_count']}` rows) | "
                f"{_format_ms(direct['p50'])} | {_format_ms(direct['p95'])} | "
                f"{_format_ms(bridge['p50'])} | {_format_ms(bridge['p95'])} | "
                f"{_format_ms(overhead['p95'])} | "
                f"{_format_ms(PGVECTOR_RECALL_P95_BUDGET_MS)} | "
                f"{_format_ms(PGVECTOR_RECALL_MAX_ADVISORY_MS)} ({advisory}) | "
                f"{pg_status} |",
            ]
        )

    if summary["budget"]["within_budget"]:
        lines.append("\nBudget result: `PASS`.")
    else:
        lines.append("\nBudget result: `FAIL`.")
        for failure in summary["budget"]["failures"]:
            lines.append(f"- {failure}")

    return "\n".join(lines)


def write_report(summary: dict[str, Any], path: Path = DEFAULT_REPORT_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    if REPORT_START not in text or REPORT_END not in text:
        raise ValueError(f"{path} is missing benchmark result markers")
    before, rest = text.split(REPORT_START, 1)
    _old, after = rest.split(REPORT_END, 1)
    generated = render_report_results(summary)
    path.write_text(
        f"{before}{REPORT_START}\n{generated}\n{REPORT_END}{after}",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark memory bridge latency against direct manager calls"
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--check-budget", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--pgvector",
        action="store_true",
        help="Also seed and measure real pgvector recall when DATABASE_URL is set",
    )
    parser.add_argument("--pgvector-iterations", type=int, default=DEFAULT_PGVECTOR_ITERATIONS)
    parser.add_argument("--pgvector-warmup", type=int, default=DEFAULT_PGVECTOR_WARMUP)
    parser.add_argument("--pgvector-seed-count", type=int, default=DEFAULT_PGVECTOR_SEED_COUNT)
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    summary = await run_benchmark(
        iterations=args.iterations,
        warmup=args.warmup,
        include_pgvector=args.pgvector,
        pgvector_iterations=args.pgvector_iterations,
        pgvector_warmup=args.pgvector_warmup,
        pgvector_seed_count=args.pgvector_seed_count,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.write_report:
        write_report(summary, args.report_path)
    if args.check_budget and not summary["budget"]["within_budget"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async(parse_args())))


if __name__ == "__main__":
    main()
