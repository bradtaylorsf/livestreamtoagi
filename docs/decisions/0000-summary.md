# Minecraft Pivot Decision Summary

Status: coding can begin

Research date: 2026-05-18

Related epic: #503, E1 - Research, Decisions & Spikes

## Non-Technical Summary

The Minecraft pivot can start coding now. The first implementation should build
a private Paper 1.21.6 server, fork/pin Mindcraft, generate bot profiles from
the existing agent configs, and build the Python-to-Node bridge.

Two things remain launch gates, not coding gates: production auth/legal posture
and the final broadcast hardening pass.

## Final Decisions

| Area | Decision | Issue |
| --- | --- | --- |
| Minecraft version | Pin `1.21.6` for E2 through E8. | #518 |
| Server software | Use Paper, artifact `paper-1.21.6-48.jar`. | #518 |
| Mindcraft pin | Fork `mindcraft-bots/mindcraft@35be480b4cc0bca990278e6103a1426392559d96`. | #518 |
| Node runtime | Use Node 20 LTS for Mindcraft. | #518 |
| Java runtime | Use Java 21 for Paper 1.21.6. | #518 |
| Local auth | Use private offline mode: Paper `online-mode=false`, Mindcraft `auth: "offline"`. | #519 |
| Production auth | Human/legal gate: prefer Microsoft-authenticated bot/camera accounts for public monetized launch unless offline-mode private topology is approved. | #519, #524 |
| Model routing | Use native Mindcraft `model` and `code_model`; validate locally with LM Studio profile strings before any OpenRouter spend. No immediate routing patch. | #520 |
| Embeddings | Do not rely on OpenRouter embeddings in Mindcraft. Use LM Studio embeddings where available, another local provider, or accept word-overlap until Python memory replaces it. | #520 |
| Conversation | Use Mindcraft pairwise bot conversations as the base. Add our own personality/proximity/eavesdrop layer. | #521 |
| Management | Never spawn Management as a bot. Keep it Python-side and out-of-band. | #521 |
| Alpha | First embodied bot, action-only/non-verbal. Block normal conversation initiation. | #521 |
| Bridge extension | Fork patch, not plugin. Add Node bridge module plus explicit commands/skills. | #522 |
| Bridge transport | Authenticated FastAPI WebSocket with versioned request/response envelopes. | #522 |
| Video capture | Production uses real Minecraft Java camera client + OBS. Prismarine Viewer is diagnostic/fallback. | #523 |
| Licensing | Proceed locally. Public launch requires unofficial disclaimer, all-ages safeguards, and auth/legal review. | #524 |

## Begin Coding Here

1. E2-1: provision Paper 1.21.6 locally with a beginner runbook.
2. E3-1: fork Mindcraft at the pinned commit and make install reproducible with
   Node 20.
3. E3-4: generate Mindcraft profiles from `agents/<id>/config.yaml`.
4. E4-1/E4-2: define the bridge envelope and implement `!bridgePing`.
5. E11 can run in parallel: add hard per-agent hourly spend caps and connect the
   kill switch plan to bot/server processes.
6. E13 capture spike can run in parallel: prove real client + OBS capture on the
   pinned server.

## Plan Reconciliation

- The original issue plan treated OpenRouter support as uncertain. Current
  Mindcraft source supports OpenRouter and separate `model`/`code_model`, and
  also has an LM Studio provider for local validation, so E3 does not need an
  immediate routing patch.
- The original issue plan said Mindcraft had no Python bridge. Current
  Mindcraft has a small `src/mindcraft-py` wrapper, but it only starts
  MindServer and creates agents. The product bridge is still new work.
- The original issue plan treated the livestream pipeline as fully greenfield.
  That remains true for production. Mindcraft's browser viewer is useful, but
  not chosen for production capture.
- The original issue plan assumed "decentralized respond/ignore" could replace
  the Python director. That remains directionally true, but the native behavior
  is pairwise and needs our layer for eavesdropping, proximity, and personality
  weighting.

## Remaining Gates

| Gate | Blocks coding? | Blocks production launch? | Owner |
| --- | --- | --- | --- |
| Offline-mode legal/auth decision | No | Yes | Human |
| Real-client OBS host choice | No | Yes | Engineering/human |
| In-game `!bridgePing` proof | Blocks E5+ | Yes | E4 |
| Public brand/disclaimer review | No | Yes | Human |

## Decision Records

- [0001: Minecraft Version And Server Software](0001-minecraft-version-and-server.md)
- [0002: Auth Mode](0002-auth-mode.md)
- [0003: Mindcraft Model Routing](0003-mindcraft-model-routing.md)
- [0004: Decentralized Conversation](0004-decentralized-conversation.md)
- [0005: Skill And Bridge Extension Point](0005-skill-extension-point.md)
- [0006: Minecraft Video Capture](0006-video-capture.md)
- [0007: Minecraft Licensing And Commercial Posture](0007-licensing.md)
