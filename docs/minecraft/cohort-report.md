# E8 Cohort Acceptance Report

Issue: #580 E8-9 - Cohort acceptance report
Epic: #510 E8 - All Agents Embodied + Decentralized Conversation
Prepared: 2026-05-20 PDT
Scope: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Alpha, Management out of band, and BridgeBot

## Decision

Status: **NO-GO for downstream fan-out epics until a full multi-hour LM Studio
soak is rerun and appended to `multi-agent-soak.md`.**

The committed E8 chain has strong static evidence: all world-bot profiles are
generated from config, launcher scripts stage local LM Studio profiles, embodied
mode gates off the Python conversation director, Mindcraft respond/ignore
metadata is present, and Management review is wired out of band before bot chat
is emitted.

The blocking gate is the E8-8 soak. `docs/minecraft/multi-agent-soak.md`
currently records a **PARTIAL LIVE STARTUP SMOKE** and says NO-GO until a full
multi-hour LM Studio soak is rerun. Post-loop manual review reached LM Studio,
started the backend, launched BridgeBot plus all eight agents, and completed a
short 0.02-hour startup smoke after fixing per-bot MindServer port collisions.
That proves startup wiring, but it is not the documented multi-hour acceptance
run. No OpenRouter validation was run or required.

This is a cohort acceptance report with an explicit rerun gate. It is not a
production livestream launch sign-off.

## Cohort Embodiment Matrix

Committed local-dev profiles use `lmstudio/__LOCAL_LLM_MODEL__` for
conversation and `lmstudio/__LOCAL_LLM_MODEL_BUILDING__` for building/code. The
production routing column below is the source mapping from
`agents/<id>/config.yaml`, cross-checked against the `CLAUDE.md` routing table
by the cohort tests.

| Runtime participant | Issue / PR | Profile | Production routing from config | `CLAUDE.md` routing label | Launcher |
| --- | --- | --- | --- | --- | --- |
| Vera | #573 / #698 | `scripts/minecraft/profiles/vera-bot.json` | `anthropic/claude-haiku-4.5` -> `anthropic/claude-sonnet-4.6` | Claude Haiku 4.5 -> Claude Sonnet 4.6 | `scripts/minecraft/connect-vera-bot.sh` |
| Rex | #573 / #698 | `scripts/minecraft/profiles/rex-bot.json` | `anthropic/claude-haiku-4.5` -> `anthropic/claude-sonnet-4.6` | Claude Haiku 4.5 -> Claude Sonnet 4.6 | `scripts/minecraft/connect-rex-bot.sh` |
| Aurora | #574 / #699 | `scripts/minecraft/profiles/aurora-bot.json` | `google/gemini-flash` -> `google/gemini-2.5-pro` | Gemini Flash -> Gemini 2.5 Pro | `scripts/minecraft/connect-aurora-bot.sh` |
| Pixel | #574 / #699 | `scripts/minecraft/profiles/pixel-bot.json` | `openai/gpt-4o-mini` -> `openai/gpt-5.2` | GPT-4o Mini -> GPT-5.2 | `scripts/minecraft/connect-pixel-bot.sh` |
| Fork | #574 / #699 | `scripts/minecraft/profiles/fork-bot.json` | `deepseek/deepseek-v3.2` -> `deepseek/deepseek-v3.2` | DeepSeek V3.2 -> DeepSeek V3.2 | `scripts/minecraft/connect-fork-bot.sh` |
| Sentinel | #575 / #700 | `scripts/minecraft/profiles/sentinel-bot.json` | `anthropic/claude-haiku-4.5` -> `anthropic/claude-haiku-4.5` | Claude Haiku 4.5 -> Claude Haiku 4.5 | `scripts/minecraft/connect-sentinel-bot.sh` |
| Grok | #575 / #700 | `scripts/minecraft/profiles/grok-bot.json` | `x-ai/grok-3-mini` -> `x-ai/grok-3` | Grok 3 Mini -> Grok 3 | `scripts/minecraft/connect-grok-bot.sh` |
| Alpha | #572 / #697; included in #579 / #704 | `scripts/minecraft/profiles/alpha-bot.json` | `deepseek/deepseek-v3.2` -> `deepseek/deepseek-v3.2` | DeepSeek V3.2 -> `-` in the table; Alpha is non-verbal/action-only | `scripts/minecraft/connect-alpha-bot.sh` |
| Management | #572 / #697; #578 / #703 | No world profile by design | `anthropic/claude-haiku-4.5`; no world `code_model` route | Claude Haiku 4.5 -> `-` | No launcher; out-of-band `management.review` only |
| BridgeBot | Included in #579 / #704 | `scripts/minecraft/profiles/bridge-bot.json` | Technical bridge support bot, local LM Studio placeholders only | Not in agent routing table | `scripts/minecraft/connect-bridge-bot.sh` |

## Child Issue Evidence

| Slice | Issue / PR / commit | Acceptance | Evidence | Status |
| --- | --- | --- | --- | --- |
| E8-1 Profile generation | #572 / #697 / `49167f0` | Generate valid profiles from `agents/<id>/config.yaml`; exclude Management as a world bot; keep model versions aligned. | `scripts/minecraft/gen_profiles.py`; `scripts/minecraft/profiles/*-bot.json`; `docs/minecraft/model-routing.md`; `pnpm verify:mindcraft-profiles`; `tests/backend/test_mc_profile_gen.py`; `tests/backend/test_mc_personality_mapping.py`. | Pass for static profile generation. |
| E8-2 Vera + Rex | #573 / #698 / `0e0218d` | Verbal Mindcraft launchers and local profiles for Vera and Rex with correct routing. | `connect-vera-bot.sh`; `connect-rex-bot.sh`; `mindcraft-settings-vera.js`; `mindcraft-settings-rex.js`; `tests/backend/test_mc_cohort1_vera_rex.py`. | Pass for committed launch/profile contracts; live action proof remains gated by E8-8. |
| E8-3 Aurora + Pixel + Fork | #574 / #699 / `4c9bbde` | Verbal Mindcraft launchers and local profiles for Aurora, Pixel, and Fork with correct routing. | `connect-aurora-bot.sh`; `connect-pixel-bot.sh`; `connect-fork-bot.sh`; corresponding settings/profile files; `tests/backend/test_mc_cohort2_aurora_pixel_fork.py`. | Pass for committed launch/profile contracts; live action proof remains gated by E8-8. |
| E8-4 Sentinel + Grok | #575 / #700 / `1e21dc5` | Verbal Mindcraft launchers and local profiles for Sentinel and Grok with correct routing. | `connect-sentinel-bot.sh`; `connect-grok-bot.sh`; corresponding settings/profile files; `tests/backend/test_mc_cohort3_sentinel_grok.py`. | Pass for committed launch/profile contracts; live action proof remains gated by E8-8. |
| E8-5 Personality mapping | #576 / #701 / `b59291d` | Map `chattiness`, `initiative`, `interrupt_tendency`, `eavesdrop_tendency`, adjacency, and related knobs into Mindcraft conversation metadata. | `docs/minecraft/personality-mapping.md`; generated `personality` blocks; `bot_responder`; `tests/backend/test_mc_personality_mapping.py`. | Pass for deterministic mapping; native enforcement gaps remain documented. |
| E8-6 Director retirement | #577 / #702 / `e75548f` | Embodied runs avoid the old Python conversation director while legacy mode still works. | `core/conversation_mode.py`; embodied-mode test in `tests/backend/test_conversation_engine.py`; `CONVERSATION_MODE=embodied`. | Pass for run-mode gate. |
| E8-7 Management out of band | #578 / #703 / `6f95e20` | Bot chat is reviewed by Management before display; failures block chat. | `scripts/minecraft/fork-src/agent/bridge/management_review.js`; `connect-*-bot.sh` chat gate patch; `docs/minecraft/bridge-contract.md`; `tests/backend/test_bridge_node_client.py`; `tests/backend/test_management.py`. | Pass for service-backed chat gate; no Management world bot. |
| E8-8 Multi-agent soak | #579 / #704 / `1dd4806` | Multi-hour local run with all bots, bridge stability, respond/ignore counts, and spend within caps. | `docs/minecraft/multi-agent-soak.md`; `scripts/minecraft/soak.sh`; `scripts/minecraft/soak.sh --verify`; `pnpm verify:minecraft-soak`; post-loop 0.02-hour live startup smoke with all bots. | **Deviation:** startup smoke only. Full multi-hour LM Studio soak is still required before fan-out. |

## Decentralized Conversation Confirmation

Mindcraft remains the conversation base for embodied runs:

1. The generated profiles contain `bot_responder` prompts and `personality`
   probabilities. `docs/minecraft/personality-mapping.md` records the mapping
   and the remaining native Mindcraft gaps.
2. `CONVERSATION_MODE=embodied` causes the Python simulation phase runner to
   avoid constructing `ConversationEngine`; the legacy director stays available
   for non-embodied and eval paths.
3. Verbal cohort settings keep `chat_ingame=true`, `chat_bot_messages=true`,
   `narrate_behavior=true`, and no spawn/init message. Alpha remains
   non-verbal with zero respond/initiate probability.
4. The E8-8 soak runner collects rough respond/ignore counters from bot logs,
   but a completed live run has not been appended yet.

## Management Boundary

Management is part of the nine-agent roster, but is intentionally not embodied
as a Minecraft world bot. The generator refuses Management as a world profile,
and E8-7 routes bot-emitted chat through `management.review` over the bridge
before visible output. Bridge failures are fail-closed, so missing Management
review blocks chat rather than leaking unreviewed text.

## Deviations And Gates

- **Live multi-hour soak missing.** The E8-8 report includes only a short
  post-loop startup smoke and remains the fan-out gate. Downstream
  E9/E10/E12/E13 work should wait for the live addendum or explicitly accept
  this risk.
- **Management review timed out in the startup smoke.** Bot logs showed
  fail-closed `management_review_event ... outcome=bridge_timeout` entries.
  The full soak should tune or explicitly accept the local Management review
  deadline before GO sign-off.
- **Local profiles are placeholders, not production OpenRouter IDs.** This is
  intentional for zero-spend validation. The generator's OpenRouter form still
  resolves from `agents/<id>/config.yaml` and is tested against `CLAUDE.md`.
- **Alpha and Management differ from normal model-table shape.** Alpha has a
  required Mindcraft `code_model` field in the profile but remains
  non-verbal/action-only. Management has no world profile or launcher.
- **BridgeBot is not a character-sheet agent.** It is a technical support bot
  for bridge validation and soak orchestration, with no `personality` block.
- **Personality metadata is not full native enforcement.** The profiles expose
  respond/initiate/eavesdrop/adjacency values, but
  `personality-mapping.md` still documents native Mindcraft gaps around full
  cadence, eavesdropping, adjacency peer selection, closing behavior, and role
  priority.

No profile/model assignment deviation was found for Vera, Rex, Aurora, Pixel,
Fork, Sentinel, or Grok against `agents/<id>/config.yaml`, `CLAUDE.md`, and
`specs/CHARACTER-SHEETS.md`.

## Local LM Studio Validation

Post-loop local command:

```bash
pnpm llm:local --list-only
```

Result:

```text
OK: connected to http://localhost:1234/v1
Models:
    text-embedding-nomic-embed-text-v1.5
    google/gemma-4-e4b
    google/gemma-4-26b-a4b
```

No OpenRouter spend was used or required.

Launcher model substitution contract:

| Launcher group | Runtime `model` | Runtime `code_model` |
| --- | --- | --- |
| `connect-alpha-bot.sh` | `lmstudio/$LOCAL_LLM_MODEL` | `lmstudio/${LOCAL_LLM_MODEL_BUILDING:-$LOCAL_LLM_MODEL}` |
| `connect-{vera,rex,aurora,pixel,fork,sentinel,grok}-bot.sh` | `lmstudio/$LOCAL_LLM_MODEL` | `lmstudio/${LOCAL_LLM_MODEL_BUILDING:-$LOCAL_LLM_MODEL}` |
| `connect-bridge-bot.sh` | `lmstudio/$LOCAL_LLM_MODEL` | `lmstudio/${LOCAL_LLM_MODEL_BUILDING:-$LOCAL_LLM_MODEL}` |
| `soak.sh` | Exports the same values to all launchers | Defaults building to conversation when unset |

Soak command to rerun when LM Studio, Paper, Node 20, Java 21, the backend, and
the bridge token are available:

```bash
export LLM_PROVIDER=lmstudio
export LOCAL_LLM_BASE_URL=http://localhost:1234/v1
export LOCAL_LLM_MODEL=<model-id-from-LM-Studio>
export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id-if-available>
export EMBEDDING_PROVIDER=deterministic
export MINECRAFT_BRIDGE_TOKEN=<same-secret-as-backend>

scripts/minecraft/soak.sh --duration-hours 2 --log-dir logs/soak
```

Nearest local smoke paths run in this E8-9 pass:

```bash
scripts/minecraft/soak.sh --verify
pnpm verify:minecraft-soak
```

Results:

- `scripts/minecraft/soak.sh --verify`: passed.
- `pnpm verify:minecraft-soak`: 15 passed.
- Post-loop live startup smoke:
  `scripts/minecraft/soak.sh --duration-hours 0.02 --log-dir /tmp/e8-8-soak-after-port-fix`
  passed with all nine bots logged in and zero early exits.

See `docs/minecraft/multi-agent-soak.md` for the live run addendum template and
the prior static evidence block.

## Sign-Off

Automated acceptance recommendation: **NO-GO for downstream fan-out epics until
the live LM Studio soak is appended and passes the E8-8 decision rule.**

Human reviewer sign-off: **pending**
Reviewer: Brad Taylor
Date: __________________ PDT
Decision: GO / NO-GO for downstream fan-out epics
