# Memory Bridge Performance

## Why This Matters

The Minecraft bridge can make several memory reads and writes around a single
perception or action cycle. In a 24/7 run, small adapter costs compound into
visible bot lag, so the bridge must stay a thin wrapper around the existing
memory managers.

## Methodology

The default benchmark is offline and deterministic:

- core read: direct `CoreMemoryManager.get_core_memory` fake vs
  `handle_memory_read` with `tier="core"`
- recall read: direct `RecallMemoryManager.retrieve_recall_memories` fake vs
  `handle_memory_read` with `tier="recall"`
- write/append: direct `MemoryCompactor.compact_interaction` fake vs
  `handle_memory_write`

The fakes match the manager methods used by `core/bridge/handlers/memory.py`.
The script forces `EMBEDDING_PROVIDER=deterministic`, uses a prebuilt
contract-valid `BridgeRequest`, discards warmup iterations, and reports p50,
p95, max, and bridge adapter overhead (`bridge - direct`).

Optional real pgvector mode runs only when `DATABASE_URL` is set. It seeds a
temporary recall namespace, measures `RecallMemoryManager.retrieve_recall_memories`
directly and through the bridge, then deletes the seeded rows.

## Budget

The source of truth for these constants is `scripts/bench_memory_bridge.py`.

| Path | Budget |
| --- | ---: |
| Bridge adapter p95 overhead, any memory operation | 2.0 ms |
| Offline bridge p95, core read | 5.0 ms |
| Offline bridge p95, recall read | 5.0 ms |
| Offline bridge p95, write/append | 5.0 ms |
| Real pgvector recall bridge p95 per action | 75.0 ms |
| Real pgvector recall max advisory per action | 250.0 ms |

If offline bridge overhead exceeds budget, the regression guard fails. If real
pgvector recall p95 exceeds 75 ms in `--pgvector` mode, file a follow-up issue
before accepting the bridge for high-frequency bot actions.

## Measured Results

<!-- benchmark-results:start -->
Generated: `2026-05-19T06:50:20+00:00`

Python: `3.13.13`
Platform: `macOS-26.4.1-arm64-arm-64bit-Mach-O`
Embedding provider: `deterministic`
Iterations: `2000` measured, `200` warmup

| Operation | Direct p50 ms | Direct p95 ms | Bridge p50 ms | Bridge p95 ms | Adapter p95 ms | Bridge p95 budget ms | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `core_read` | 0.0003 | 0.0004 | 0.0023 | 0.0024 | 0.0020 | 5.0000 | PASS |
| `recall_read` | 0.0003 | 0.0004 | 0.0021 | 0.0022 | 0.0019 | 5.0000 | PASS |
| `write_append` | 0.0003 | 0.0004 | 0.0013 | 0.0014 | 0.0010 | 5.0000 | PASS |

Adapter overhead p95 budget: `2.0 ms`.

Real pgvector recall: not run in this report. Use `python scripts/bench_memory_bridge.py --pgvector --check-budget` with `DATABASE_URL` set to exercise a seeded temporary recall namespace.

Budget result: `PASS`.
<!-- benchmark-results:end -->

## Pgvector Per-Action Assessment

The committed benchmark always checks deterministic bridge overhead. The real
pgvector recall path is opt-in because it needs a migrated PostgreSQL database.
When available, run:

```bash
python scripts/bench_memory_bridge.py --pgvector --check-budget --write-report
```

The script seeds temporary recall rows, so the pgvector assessment does not
depend on preexisting simulation data. A p95 over 75 ms should be treated as
too slow per bot action and tracked as a follow-up performance issue.

## Local LM Studio Validation

This issue has no LLM runtime path. It benchmarks memory adapter plumbing with
deterministic embeddings and does not call OpenRouter or LM Studio models.

Nearest local validation:

```bash
pnpm llm:local --list-only
make bench-memory-bridge
pnpm verify:memory-bridge-perf
```

Record the LM Studio reachability result, model IDs if listed, and benchmark
output in the issue or PR. If LM Studio is not running on the local Mac server,
the benchmark remains valid because it has no model dependency, but that
reachability failure should be called out.

## Reproduce

```bash
make bench-memory-bridge
```

To refresh this report after a local run:

```bash
python scripts/bench_memory_bridge.py --check-budget --write-report
```
