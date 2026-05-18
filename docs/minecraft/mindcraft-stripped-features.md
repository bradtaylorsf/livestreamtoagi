# Stripped / Disabled Mindcraft Features

This runbook is the **documented list of disabled Mindcraft features + their
rationale** (the primary E3-5 acceptance criterion). It reduces Mindcraft's
surface area and cost by turning **off** the features the Python "brain" already
owns, while a bot **still connects and acts** against the E2 server with them
off.

> **Issue:** E3-5 (epic E3, [#537](https://github.com/bradtaylorsf/livestreamtoagi/issues/537)).
> **Template:** `scripts/minecraft/mindcraft-settings-stripped.js`.
> **Script:** `scripts/minecraft/connect-stripped-bot.sh`.
> **Builds on:** the stock-bot connect (E3-2 / [#534](https://github.com/bradtaylorsf/livestreamtoagi/issues/534), `docs/minecraft/mindcraft-connect.md`) and per-agent routing (E3-3 / [#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535), `docs/minecraft/model-routing.md`) — the E2-server connect contract is preserved **unchanged**.
> **Decisions bound:** `docs/decisions/0003-mindcraft-model-routing.md` (memory/embeddings/voice/vision are Python-side), `docs/decisions/0004-decentralized-conversation.md` (keep Mindcraft's decentralized conversation).

## Why (scope)

> **In:** disable Mindcraft features superseded by the Python brain (its own
> memory/persona/voice if redundant) per E1-R3/R4, **behind config flags,
> reversible**.
> **Out:** irreversible deletion of fork core.

Mindcraft ships its own example/skill-doc retrieval, auto-narration, session
memory, voice (TTS), and vision. The Python side owns the equivalents (3-tier
pgvector memory, what is surfaced/streamed, Edge TTS) — running both is wasted
tokens, wasted latency, and a second source of truth. We therefore turn the
redundant Mindcraft features **off**.

**The Mindcraft `settings.js` keys *are* the reversible config flags.** Flipping
a value back re-enables the feature with **no fork-core edit** — that is exactly
why this stays in scope ("Out: irreversible deletion of fork core"). The
stripped template `scripts/minecraft/mindcraft-settings-stripped.js` is a
faithful copy of the reviewed E3-2 stock template
(`scripts/minecraft/mindcraft-settings.js`), with **only** the keys below
changed (each flagged `E3-5:` inline) and **every other key byte-identical** so
Mindcraft never reads an undefined setting and the E2 contract is intact.

## Disabled features (the list + rationale + how to reverse)

| Feature | Mindcraft setting — value delta (vs. E3-2 stock template) | Superseded by (Python system + decision) | How to reverse |
|---|---|---|---|
| In-context example retrieval | `num_examples` **`2` → `0`** | Python 3-tier memory service supplies relevant context. Decision **0003** explicitly says *disable/de-emphasize Mindcraft examples until E5*; Mindcraft's OpenRouter class has **no embeddings** so retrieval is degraded anyway. | Set `num_examples` back to `2` in `mindcraft-settings-stripped.js` (or use the E3-2 stock template). |
| Skill-doc retrieval | `relevant_docs_count` **`5` → `0`** | Same Python 3-tier memory service owns relevant-doc selection (decision **0003**); no embedding provider at the pinned commit. | Set `relevant_docs_count` back to `5` (`-1` = all). |
| Automatic behavior narration | `narrate_behavior` **`true` → `false`** | Python owns **what is surfaced/streamed** (decision **0004** keeps Python the source of truth for surfaced output). Mindcraft auto-chatting `Picking up item!` is redundant noise on-stream. | Set `narrate_behavior` back to `true`. |
| Cross-session bot memory | `load_memory` **`false`** *(already upstream-false; affirmed)* | Mindcraft session memory → the Python **3-tier pgvector memory** service (E5 / decision **0003** — do not rely on Mindcraft for memory). | Set `load_memory` to `true`. |
| Text-to-speech (voice) | `speak` **`false`** *(already upstream-false; affirmed)* | Voice is owned by the **Python Edge TTS** pipeline, not Mindcraft (decision **0003** keeps voice Python-side). | Set `speak` to `true` (and configure a speech model per the upstream notes in the template). |
| Vision tier | `allow_vision` **`false`** *(already upstream-false; affirmed)* | No Mindcraft vision tier in the pivot — unused; cost/surface reduction (decision **0003**). | Set `allow_vision` to `true`. |

`num_examples`, `relevant_docs_count`, `narrate_behavior` are **actual value
deltas** vs. the E3-2 stock template. `load_memory`, `speak`, `allow_vision`
are already `false` upstream — E3-5 does **not** change their value; it records
**why** we keep them off and the Python system that supersedes each (a clear,
annotated decision binding, still trivially reversible). The structural diff is
enforced by `tests/backend/test_mc_stripped_features.py`: the parsed settings
object differs from the E3-2 stock template in **exactly** these three keys and
**no others**.

## Deliberately KEPT (NOT stripped)

| Kept ON | Setting | Why |
|---|---|---|
| Decentralized bot-to-bot conversation | `chat_bot_messages` **`true`** + the Mindcraft conversation system | Decision **0004** keeps Mindcraft's decentralized **pairwise** conversation as the **base** (replacing the old Python central speaker director). Stripping it would remove the very behaviour the pivot is built on. The personality/proximity/eavesdrop layer on top of it is **E8** new work, not removal. |

This is an explicit non-strip: the test asserts `chat_bot_messages` stays
`true` and that the conversation system is **not** disabled.

## Known gap — deferred to E8 / the bridge (out of scope for E3-5)

Mindcraft's **persona / `base_profile` prompt scaffolding** (the `assistant`
base profile prompt, the built-in conversational system prompt) **cannot be
fully neutralised at the pinned commit without a fork patch**. There is no
`settings.js` flag that disables Mindcraft's own persona prompt, and E3-5's
scope is explicitly *"Out: irreversible deletion of fork core"* — so a
prompt-level fork patch is **not** done here.

This is acceptable for E3-5 because:

- The acceptance criterion is *a bot still connects and acts with the disabled
  features off* — it does (see verification below).
- Our nine agents and their personas are **E8**; the bridge that injects
  Python-owned persona/memory/Management is **E4** (decision 0004's *Mapping
  From Existing Agent Knobs* table — energy, eavesdrop, proximity, Management
  all "Needs our layer / Needs E4/E8"). Neutralising or replacing Mindcraft's
  persona prompt belongs to that bridge work, tracked by the epic, **not** E3-5.

If a later epic decides the residual `base_profile` prompt must go, it is a
fork patch tracked under E3-7 ([#539](https://github.com/bradtaylorsf/livestreamtoagi/issues/539)) /
the bridge (E4), governed by `docs/minecraft/fork-maintenance.md`.

## Verify a bot still connects & acts with the features off

The E2 connect contract is **byte-identical** to the E3-2 stock template
(host `127.0.0.1`, port `25565`, `auth: "offline"`, `minecraft_version:
"1.21.6"`, `profiles: ["./profiles/stock-bot.json"]`), so `connect-stripped-bot.sh`
connects exactly like `connect-stock-bot.sh` — only the disabled features differ.

### Static verify (no Node, no network, no clone)

```bash
pnpm verify:mindcraft-stripped
# shorthand for: .venv/bin/pytest tests/backend/test_mc_stripped_features.py -v
```

There is also a script-level static check that needs nothing but `bash`:

```bash
scripts/minecraft/connect-stripped-bot.sh --verify
```

It prints the disabled-feature flags **and** the preserved E2 target, asserts
the stripped template still points at the E2 server, that the E3-5 features are
disabled, and that `chat_bot_messages` is **kept** (decision 0004).

### Preview the resolved plan (no launch)

```bash
scripts/minecraft/connect-stripped-bot.sh --dry-run
```

### Real local run (LM Studio — zero external spend, decision 0003)

Prerequisites are the same as the E3-2 connect (`docs/minecraft/mindcraft-connect.md`):
E2 server running, the pinned fork installed (`scripts/minecraft/setup-mindcraft.sh`),
**Node 20 LTS**, and LM Studio serving on `http://localhost:1234/v1`.

```bash
pnpm llm:local --list-only          # confirm LM Studio + list served ids
export LOCAL_LLM_MODEL=<model-id-from-the-list>
# Optional larger building/code-tier model when available:
export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>

scripts/minecraft/connect-stripped-bot.sh
```

The script stages `mindcraft-settings-stripped.js` → `./mindcraft/settings.js`
(host/port/profile substituted), reuses and stages
`scripts/minecraft/profiles/stock-bot.json` (LM Studio ids substituted), applies
the same launch-time runtime-version shim as `connect-stock-bot.sh` (restored on
exit), prints the **whitelist** command for `StockBot`, then launches:

```text
cd ./mindcraft && node main.js --profiles ./profiles/stock-bot.json
```

**Success looks like** (identical to E3-2, proving the features-off bot still
acts): `StockBot joined the game` in the E2 console, `StockBot` in `list`, and
the bot moving in-world (e.g. `StockBot !moveAway(10)` from a normal client).

## Required LM Studio evidence checklist

Record the following in the issue/PR (no OpenRouter spend is required for
acceptance — decision 0003):

- [ ] **LM Studio reachable:** output of `pnpm llm:local --list-only`
      (or `.venv/bin/python scripts/check_local_llm.py --list-only`).
- [ ] **The model id(s) used** for `LOCAL_LLM_MODEL`
      (and `LOCAL_LLM_MODEL_BUILDING` if set).
- [ ] **The exact command(s) run** (`scripts/minecraft/connect-stripped-bot.sh`,
      the `whitelist add StockBot` console command).
- [ ] **Ran against the local Mac server** (E2 Paper on `127.0.0.1:25565`,
      `online-mode=false`).
- [ ] **`StockBot` connected and acted** with the E3-5 features off
      (server-console join line + `list` + a visible action).

> A real connect needs Node 20 + a running E2 server + LM Studio. On a host
> without those, `pnpm verify:mindcraft-stripped` /
> `scripts/minecraft/connect-stripped-bot.sh --verify` are the nearest local
> smoke paths and are what CI / the automated verifier runs. If no LLM runtime
> is available, state that explicitly and attach the static-verify output
> instead.

## Where this is recorded

- **`scripts/minecraft/mindcraft-settings-stripped.js`** — the stripped settings
  template (the reversible config flags; each change flagged `E3-5:` inline).
- **`scripts/minecraft/connect-stripped-bot.sh`** — the launch script that
  stages it and proves a bot still connects/acts with the features off.
- **`docs/decisions/0003-mindcraft-model-routing.md`** — memory/embeddings/voice
  /vision are Python-side; disable/de-emphasize Mindcraft examples until E5.
  Back-references E3-5/#537.
- **`docs/decisions/0004-decentralized-conversation.md`** — keep Mindcraft's
  decentralized conversation as the base (the deliberately-KEPT feature).
  Back-references E3-5/#537.
- **`tests/backend/test_mc_stripped_features.py`** — the headless,
  dependency-free contract test: exactly these flags flip and only these, the
  E2 contract is byte-preserved, `chat_bot_messages` is kept, and this doc
  enumerates every disabled feature with rationale + reversibility + a
  decision 0003/0004 cross-reference (`pnpm verify:mindcraft-stripped`).

### Related

- **`docs/minecraft/mindcraft-connect.md`** — the E3-2 stock-bot connect this
  builds on (same E2 contract; only the disabled features differ).
- **`docs/minecraft/model-routing.md`** — the E3-3 per-agent multi-model
  routing verification (same committed-artifact + staged-into-clone pattern).
- **`docs/minecraft/fork-maintenance.md`** — branch/upstream-merge policy that
  governs any later persona-prompt fork patch (the known gap above).
