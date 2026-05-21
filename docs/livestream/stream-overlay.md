# Stream Overlay: Agent Labels + Status

> **Issue:** E13-3 (epic E13, [#611](https://github.com/bradtaylorsf/livestreamtoagi/issues/611)).
> **Files:** `core/public_routes.py`, `scripts/livestream/overlay/`,
> `scripts/livestream/serve-overlay.sh`.
> **Builds on:** E13-1 for the Minecraft capture source. This overlay is the
> OBS browser-source replacement for the retired Phaser overlay in
> `frontend/src/ui/StreamOverlay.ts`.

## What This Is

This is a transparent browser overlay for OBS. It renders a top status bar and
a right-side agent list over the Minecraft capture. The browser source polls
the Python brain every second:

```text
GET http://127.0.0.1:8010/api/stream/agent-status
```

The response is intentionally small:

```json
{
  "agents": [
    {
      "id": "vera",
      "display_name": "Vera",
      "status": "talking",
      "last_action_at": "2026-05-21T12:00:00+00:00",
      "current_topic": "bridge setup"
    }
  ],
  "updated_at": "2026-05-21T12:00:01+00:00"
}
```

`status` is always one of `idle`, `talking`, `building`, `active`, `waiting`,
or `error`.

## What This Is Not

- It does not capture Minecraft video. That belongs to E13-1.
- It does not encode or push RTMP to Twitch/YouTube. That belongs to E13-2.
- It does not add TTS/audio. That belongs to E13-4.
- It does not restart failed capture/encoder processes or implement the kill
  path. Those belong to E13-5 and E13-6.

## Prerequisites

Start the backend on port 8010:

```bash
pnpm dev:backend
```

The endpoint reads the agent registry plus recent backend event-bus history,
agent internal state, and the latest transcript rows when available. It is
CORS-permissive for local OBS browser sources and sends `Cache-Control:
no-store, max-age=0` so polling is live rather than cached.

## Run It

Serve the overlay locally:

```bash
scripts/livestream/serve-overlay.sh
```

Default OBS browser source URL:

```text
http://127.0.0.1:8765/index.html?api=http://127.0.0.1:8010
```

Useful knobs:

```bash
STREAM_OVERLAY_PORT=8766 scripts/livestream/serve-overlay.sh
scripts/livestream/serve-overlay.sh --port 8766 --api http://127.0.0.1:8010
```

Dry-run smoke:

```bash
scripts/livestream/serve-overlay.sh --check
```

`--check` starts a temporary static server, fetches `index.html`, fetches the
backend status endpoint, prints the OBS URL, and exits 0 on success or 2 on
check failure.

## OBS Setup

Add a Browser source:

- URL: `http://127.0.0.1:8765/index.html?api=http://127.0.0.1:8010`
- Width/height: match the stream canvas, usually 1920x1080.
- Background: transparent; the HTML body is `background: transparent`.
- Hardware acceleration: keep enabled unless the capture host shows browser
  source rendering artifacts.

The source should sit above the Minecraft capture source and below any
emergency full-screen slate added by later E13 kill/resilience work.

## Status Mapping

The mapping mirrors the retired Phaser `StreamOverlay` event handling:

| Python event | Overlay status |
|--------------|----------------|
| `agent_speak` | `talking` |
| `agent_action` with `action=building` or `action=coding` | `building` |
| other `agent_action` | `idle` |
| `tool_executed` | `active` |
| `management_shadow` or `management_warning` | `waiting` |
| `management_intervention` | `error` |

Minecraft bridge events are mapped without assuming gameplay facts:

| Python event | Overlay status |
|--------------|----------------|
| `bridge_perception` | `active` |
| successful or in-progress `bridge_action_result` | `active` |
| failed/rejected `bridge_action_result` | `error` |

If no recent event exists for an agent, the endpoint falls back to the agent
registry and internal state. Registry `active` becomes overlay `idle`; paused,
sleeping, or muted agents become `waiting`. Very low energy internal state also
shows as `waiting`.

## Acceptance Evidence

For issue/PR evidence, record:

```bash
pnpm verify:livestream-overlay
scripts/livestream/serve-overlay.sh --check
```

Then start OBS or a browser pointed at:

```text
http://127.0.0.1:8765/index.html?api=http://127.0.0.1:8010
```

Confirm that the right sidebar lists the live agent registry and that a backend
event such as `agent_speak` changes the displayed status.

## Local LM Studio Validation

This overlay has no LLM runtime path: it only serves static HTML/CSS/JS and
polls a read-only backend status endpoint. For the E13 local-model evidence,
still confirm the local server state separately and record it:

```bash
pnpm llm:local --list-only
```

If LM Studio is not running, record that result and use the nearest local smoke
path instead:

```bash
pnpm verify:livestream-overlay
scripts/livestream/serve-overlay.sh --check
```

Do not require OpenRouter spend for this issue.

## Documented Limitations

- The overlay is an OBS browser source, not an ffmpeg burn-in filter.
- It polls once per second; it is not a WebSocket client.
- `--check` requires the backend status endpoint to be reachable on the
  configured `--api` URL.
- Capture, audio, resilience, stream health, and kill-switch behavior remain
  separate E13 issues.
