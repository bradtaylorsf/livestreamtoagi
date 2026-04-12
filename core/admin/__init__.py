"""Admin API package.

Assembles all domain sub-routers into a single admin_router
mounted at /api/admin with bearer-token authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.admin.agent_routes import router as agent_router
from core.admin.artifact_routes import router as artifact_router
from core.admin.auth_routes import router as auth_router
from core.admin.config_routes import router as config_router
from core.admin.conversation_routes import router as conversation_router
from core.admin.dependencies import require_admin
from core.admin.diagnostics_routes import router as diagnostics_router
from core.admin.eval_routes import _background_tasks, router as eval_router
from core.admin.kill_switch_routes import router as kill_switch_router
from core.admin.simulation_routes import router as simulation_router

admin_router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(require_admin)],
)

admin_router.include_router(agent_router)
admin_router.include_router(artifact_router)
admin_router.include_router(config_router)
admin_router.include_router(conversation_router)
admin_router.include_router(diagnostics_router)
admin_router.include_router(eval_router)
admin_router.include_router(simulation_router)

# Kill switch uses its own KILL_SWITCH_API_KEY auth, mounted separately
# so it doesn't require the general admin password.
kill_switch_api = APIRouter(prefix="/api/admin")
kill_switch_api.include_router(kill_switch_router)

# Auth routes (login/logout) don't require existing admin auth.
auth_api = APIRouter(prefix="/api/admin")
auth_api.include_router(auth_router)

__all__ = ["admin_router", "kill_switch_api", "auth_api", "_background_tasks"]
