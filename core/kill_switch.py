"""Shared global kill-switch constants.

The kill switch is intentionally not simulation-scoped. It is written by the
admin emergency route and read by runtime safety paths that need the same
process-wide state.
"""

KILL_SWITCH_KEY = "kill_switch"
KILL_SWITCH_ACTIVE_VALUE = "active"
