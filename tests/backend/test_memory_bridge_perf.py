"""Regression guard for memory bridge performance reporting (issue #555, E5-7)."""

from __future__ import annotations

from scripts import bench_memory_bridge as bench


async def test_offline_bridge_paths_match_direct_fake_backend() -> None:
    results = await bench.collect_parity_results()

    assert results == {
        "core_read": {
            "direct": "## My Core Memory\n\n### Who I am\nVera keeps the bridge honest.",
            "bridge": "## My Core Memory\n\n### Who I am\nVera keeps the bridge honest.",
        },
        "recall_read": {
            "direct": "## Relevant memories\n- [event] Rex built a spawn bridge.",
            "bridge": "## Relevant memories\n- [event] Rex built a spawn bridge.",
        },
        "write_append": {
            "direct": "1",
            "bridge": "1",
        },
    }


async def test_offline_benchmark_summary_is_well_formed_and_within_budget() -> None:
    summary = await bench.run_benchmark(iterations=160, warmup=20)

    assert summary["metadata"]["benchmark"] == "memory_bridge_performance"
    assert summary["metadata"]["embedding_provider"] == "deterministic"
    assert summary["offline"]["iterations"] == 160
    assert summary["offline"]["warmup"] == 20
    assert set(summary["offline"]["operations"]) == {
        "core_read",
        "recall_read",
        "write_append",
    }

    for name, result in summary["offline"]["operations"].items():
        assert result["samples"] == 160
        assert set(result) == {
            "direct_ms",
            "bridge_ms",
            "adapter_overhead_ms",
            "samples",
        }
        assert result["bridge_ms"]["p95"] <= bench.OFFLINE_BRIDGE_P95_BUDGET_MS[name]
        assert result["adapter_overhead_ms"]["p95"] <= bench.BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS

    assert summary["budget"] == bench.evaluate_budget(summary)
    assert summary["budget"]["within_budget"], summary["budget"]["failures"]


async def test_adapter_overhead_mean_has_generous_absolute_and_relative_guard() -> None:
    offline = await bench.run_offline_benchmark(iterations=220, warmup=25)

    for result in offline["operations"].values():
        direct_mean = max(result["direct_ms"]["mean"], 0.001)
        overhead_mean = result["adapter_overhead_ms"]["mean"]
        generous_bound = max(
            bench.BRIDGE_ADAPTER_OVERHEAD_P95_BUDGET_MS,
            direct_mean * 20,
        )

        assert overhead_mean <= generous_bound
