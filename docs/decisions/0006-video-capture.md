# Decision 0006: Minecraft Video Capture

Status: accepted for coding

Research date: 2026-05-18

Related issue: #523, E1-R6

## Non-Technical Summary

For the real livestream, use a real Minecraft Java client as the camera and
capture that with OBS. This costs more operationally than a web renderer, but it
avoids version/rendering bugs and produces the actual Minecraft look viewers
expect.

Mindcraft's browser viewer is still useful for diagnostics and maybe a cheap MVP
recording path, but it should not be the production stream dependency.

## Decision

- Production capture method: real Minecraft Java client in spectator/camera role
  plus OBS Studio.
- Camera identity: a separate `camera` user/client, not one of the 9 agents.
- Initial camera control: manual or scripted spectator positioning.
- Later camera control: Python decides active subject; server/RCON or client
  automation moves the camera.
- Broadcast pipeline: OBS captures the Minecraft client window and overlays
  browser sources from the existing website/admin status surfaces.
- Streaming output: OBS RTMP to Twitch/YouTube/Restream.
- Diagnostic fallback: Mindcraft `render_bot_view=true` / Prismarine Viewer on
  localhost for bot POV debugging.
- Emergency fallback: browser-view capture if the real client/OBS stack is not
  available, but only after validating visual correctness for the pinned
  Minecraft version.

## Why Not Prismarine Viewer For Production

Mindcraft can expose bot views in a browser on localhost ports `3000`, `3001`,
etc. Prismarine Viewer is attractive because it is scriptable and browser-based.
However, there is an open Prismarine Viewer issue for `1.21.5+` support where
users report incorrect block rendering on newer versions. Since decision 0001
pins `1.21.6`, the viewer is too risky as the production broadcast source.

This does not invalidate it for tests or internal debugging.

## Hosting Implications

The production host needs:

- A display-capable environment for the Minecraft client and OBS.
- GPU acceleration if we want stable 1080p/30fps or better.
- Java 21 for the server and the matching Java Edition client.
- OBS Studio with WebSocket enabled for automation.
- Process supervision for server, Mindcraft, backend, client, and OBS.
- Disk budget for local recording buffers.

For local development, the first stream spike can run on the owner's machine.
For 24/7 production, use a dedicated GPU-capable host or a local machine that is
allowed to run continuously.

## Camera Rules

- The camera is not an agent and has no memory/personality.
- The camera must not interact with the world except for movement/viewpoint.
- The camera may use spectator mode if available.
- The stream overlay should identify active agents, current goals, costs, and
  safety/kill status from Python, not from the camera client.

## Fallback Plan

If real-client OBS capture is too costly or unstable:

1. Test Prismarine Viewer on the pinned `1.21.6` world.
2. If textures are wrong, either patch Prismarine Viewer texture/version support
   or temporarily move the capture-only stack to a viewer-supported Minecraft
   version.
3. If OBS is unstable, capture the client/window with ffmpeg and keep overlays
   as a browser/compositor layer.

## Evidence

- Mindcraft `render_bot_view` setting:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/settings.js#L39-L45
- Mindcraft browser viewer wiring:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/vision/browser_viewer.js#L1-L8
- Prismarine Viewer project and mineflayer viewer API:
  https://github.com/PrismarineJS/prismarine-viewer
- Prismarine Viewer `1.21.5+` support issue:
  https://github.com/PrismarineJS/prismarine-viewer/issues/473
- OBS Browser Source docs:
  https://obsproject.com/kb/browser-source
- OBS WebSocket remote-control docs:
  https://obsproject.com/kb/remote-control-guide
