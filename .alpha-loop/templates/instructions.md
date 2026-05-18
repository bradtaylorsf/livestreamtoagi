<!-- managed by alpha-loop -->
Updated `AGENTS.md` to match the current codebase (138 lines, marker intact, 5-section structure preserved).

Key corrections made after verifying against the actual tree:

- **Public API is now live**: added `core/public_routes.py` (`prefix=/api`, ~54 endpoints) and removed every stale "not yet implemented / planned routes" claim — including the non-negotiable that previously asserted the website's API wasn't served.
- **Migrations**: 37 → **48** (latest is `048_simulation_video_failure_reason`, not 047 as a prior changelog note guessed).
- **Repos**: 17 → **19** (added `challenge_repo`, `user_repo`; noted `repos/utils.py`).
- **Admin endpoints**: 63 → **66** (still 9 route modules).
- **Pydantic models**: ~101 → **~107**.
- **New subsystems documented**: `core/auth/` (email magic-link user auth), `core/notifications/`, `core/video/` (sim→MP4 render pipeline), `core/youtube/` (publishing); memory additions `dreams.py`, `memory_seed.py`.
- **Sandbox**: top-level `sandbox/Dockerfile` plus the `sandbox` docker-compose service.
- **`scenarios/`** directory added (18 scenario YAMLs).
- **Website**: replaced the "admin dashboard UI" description with the real public page list; `api.ts` now documented as consuming live routes.
- **Tools**: 32 → **33** tool classes; **scripts/** refreshed with `render_simulation_video.py`, `publish_simulation_youtube.py`, `backfill_*.py`, `verify-render.sh`.
- **evals/**: corrected 13 → **12** eval prompts (`_analyzer.yaml` is config, not a category).
- **main.py surface**: added `/videos/{filename}`, public `/api/*`, and user/admin auth routers.

Preserved: the `<!-- managed by alpha-loop -->` marker as line 1, the 9-agent roster, the special `management`/`alpha` rules, the CrewAI-not-wired caveat, and all model/port-sync non-negotiables. I softened the ruff line (`target-version`/`line-length` weren't locatable in `pyproject.toml` via the expected keys, so I avoided asserting specifics I couldn't verify).
