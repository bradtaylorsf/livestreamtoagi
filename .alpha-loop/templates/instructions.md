<!-- managed by alpha-loop -->
Updated AGENTS.md. Key changes from the previous version:

- **Migrations**: 12 → 13 (added `013_eval_tables`)
- **Repos**: 8 → 9 (added `eval_repo`)
- **Tool classes**: 18 → 19 (accurate count from codebase)
- **Event types**: 16 → 17 (added `ARTIFACT_CREATED`)
- **Test files**: ~46 → ~52
- **Eval engine**: Added `core/eval/` subpackage (engine, loader, prompt_loader)
- **Simulation**: Expanded to reference `core/simulation/` subpackage (clock, phases, display, orchestrator)
- **Scripts**: Added `run_eval.py` and `check_tool_coverage.py` to directory listing
- **Non-negotiables**: Added `scripts/run_eval.py` as the eval entry point
- **Preserved**: All project-specific rules, special agent handling, port alignment, 5-section structure, managed-by marker
