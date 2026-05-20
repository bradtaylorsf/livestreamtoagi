<!-- managed by alpha-loop -->
`AGENTS.md` updated. Summary of what changed:

**Preserved** — the 9-agent roster, the special `management`/`alpha` rules, the 5-section structure, all repo/admin/public-route/scenario/eval counts that verified correct (48 migrations, 19 repos, 9 admin modules / 66 endpoints, ~54 public routes, 18 scenarios, 12 eval prompts + `_analyzer.yaml`, 32 tool classes), and the existing port/model-sync non-negotiables.

**Added (major)** — the **Minecraft pivot**, which the old file omitted entirely and is the biggest current reality in the tree:
- `core/bridge/` Python↔Node bridge (wired into `core/main.py`: `bridge_router`, `/api/minecraft/bridge/ws`, fail-closed auth, versioned contract, memory consumers)
- `mindcraft/` vendored/forked Mindcraft (Node 20, Mineflayer, Paper 1.21.6)
- `docs/` ADRs (`docs/decisions/` 0000–0010, binding) + `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` + `docs/minecraft/` runbooks
- `scripts/minecraft/` pivot tooling; LM Studio local-LLM acceptance path
- New non-negotiables: ADRs are binding, the bridge contract is single-source-of-truth, no hardcoding unverified Minecraft facts

**Corrected stale counts/facts** — models `~108` → `~107` (verified `class .*(BaseModel)` = 107); event types `~24` → `~26`; the wrong claim that `tests/` contains `frontend/` and `website/` subdirs (it only holds `backend/` + `integration/`, ~148 Python files; frontend vitest lives under `frontend/src/`, website vitest+Playwright under `website/`); reframed the Phaser `frontend/` as the legacy renderer during the pivot.

**Removed** — the stray second `<!-- managed by alpha-loop -->` annotation block ("The file is accurate except four counts…"); its corrections are now folded directly into the prose. The marker remains the very first line, and the file is ~150 lines with no testing/git/review/security procedures (those stay in skills).
