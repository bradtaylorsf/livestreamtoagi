<!-- managed by alpha-loop -->
Updated `AGENTS.md` to reflect the current codebase. Key changes:

- **Public API now exists**: `core/public_routes.py` is wired into `core/main.py` and serves the website (`/scenarios`, `/agents`, `/conversations`, `/blog`, `/evals`); removed the stale claim that public-facing routes weren't implemented.
- **Migration count**: bumped from 37 → 47 (latest is `047_simulation_youtube_publish`).
- **Repos**: 17 → 19 (added `challenge_repo`, `user_repo`).
- **New subsystems**: `core/auth/`, `core/notifications/`, `core/video/`, `core/youtube/`, plus memory additions (`dreams.py`, `memory_seed.py`).
- **Sandbox**: top-level `sandbox/Dockerfile` for code execution.
- **Scenarios directory**: added to layout (18 YAML scenarios + seeds/).
- **New scripts**: `render_simulation_video.py`, `publish_simulation_youtube.py`, several `backfill_*` scripts.
- **Website routes**: replaced the "admin dashboard UI" description with the actual public route list (about, agents, artifacts, blog, etc.).
- **Admin endpoint count**: 63 → 66 (counted via `@router` decorators).
- **Pydantic model count**: ~101 → ~109.
- File is 110 lines, well under the 150-line cap. All non-negotiables and special agent rules preserved.
