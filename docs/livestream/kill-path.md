# Livestream Kill Path

Issue #614 wires the global emergency kill switch to the public livestream.

## Contract

The kill switch key is the global Redis key `kill_switch`. It is not scoped to a
simulation. When the value is `active`, the livestream must enter a safe public
state on the next monitor poll:

- `holding_card`: replace the live program feed with the configured holding card.
- `cut`: terminate the RTMP push process.

When the key is absent or no longer `active`, the controller is allowed to leave
safe state. Repeated polls are idempotent, so an already-safe stream is not cut
again.

## Runtime Wiring

`core/main.py` starts the monitor only when `LIVESTREAM_ENABLED=true`. The
monitor uses the raw Redis client from `bootstrap_services()`, matching the
admin kill route and bridge kill gate. It does not use `ScopedRedis`.

Current default controller:

- `NullStreamController`: logs the safe-state transition and records the reason.
  This is the safe default until the encoder/RTMP controller is owned in the
  livestream service.

E13-2 should instantiate `RtmpStreamController` from
`core.livestream.stream_controller` with the live ffmpeg/RTMP process and
holding-card callback before constructing `KillSwitchMonitor`. If an encoder is
registered after FastAPI startup, recreate `app.state.livestream_kill_switch_monitor`
with the RTMP controller; replacing only `app.state.livestream_controller` does
not update the already-running monitor.

## Configuration

- `LIVESTREAM_ENABLED=true`: start the kill-switch monitor in FastAPI lifespan.
- `LIVESTREAM_KILL_MODE=holding_card|cut`: default `holding_card`.
- `LIVESTREAM_HOLDING_CARD=/path/to/card.png`: image used by the encoder when
  holding-card mode is wired.
- `LIVESTREAM_SAFE_TRANSITION_SECONDS=0`: reserved transition duration for the
  encoder/overlay implementation.

The default poll interval is one second, so the documented recovery window is
one poll plus controller transition time. Redis lookup failure fails closed by
treating the kill switch as active.

## Validation Notes

This path has no LLM runtime dependency. For local acceptance, verify LM Studio
reachability separately, then run the focused livestream unit tests.
