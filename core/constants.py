"""Project-wide constants."""

from __future__ import annotations

import uuid

# Well-known UUID for the persistent live simulation.
# Seeded by migration 035. All live/production data uses this simulation_id.
LIVE_SIMULATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
