# Per-Agent Multi-Model Routing (Verification)

This runbook proves the conclusion of **decision 0003** (E1-R3 / [#520](https://github.com/bradtaylorsf/livestreamtoagi/issues/520)):
Mindcraft routes a **conversation-tier `model`** and a **distinct
building-tier `code_model`** *per bot* — **natively, with no fork patch**.

> **Issue:** E3-3 (epic E3, [#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535)).
> **Script:** `scripts/minecraft/verify-model-routing.sh`.
> **Builds on:** the stock-bot connect (E3-2 / [#534](https://github.com/bradtaylorsf/livestreamtoagi/issues/534), `docs/minecraft/mindcraft-connect.md`) — the E2-server contract is preserved unchanged.
> **Scope:** **two** bots only. Mapping all nine production agents is **E3-4
> ([#536](https://github.com/bradtaylorsf/livestreamtoagi/issues/536)) / E8** — explicitly *not* this issue.

## Outcome: native routing, no fork patch

`docs/decisions/0003-mindcraft-model-routing.md` (status: accepted for coding)
already established that at the pinned fork commit
`35be480b4cc0bca990278e6103a1426392559d96`:

- Mindcraft's `Prompter` constructs **separate chat and code models** from each
  profile (`model` → conversation tier, `code_model` → building/code tier).
- LM Studio **and** OpenRouter are **native, supported providers** — the
  `{provider}/<model>` profile string syntax selects them with no code change.

This issue **verifies** that conclusion with two concrete bots and **does not
add a fork patch**. Any later patches (cost-gating, Management review, profile
`params`) are tracked separately — see decision 0003 *"Patch Scope"* and E3-7
([#539](https://github.com/bradtaylorsf/livestreamtoagi/issues/539)).

## E3-7 ([#539](https://github.com/bradtaylorsf/livestreamtoagi/issues/539)) — conditional premise not met (no patch to harden)

E3-7 is conditional: *"Only if E1-R3 concluded a patch is required and E3-3 was
non-trivial."* Neither holds — decision 0003 *"Patch Scope"* concluded **no
fork patch is required**, and E3-3 verified native routing **with no patch**.
So there is **no routing patch to harden**.

The acceptance criterion (*"tests fail if per-agent/per-tier routing breaks"*)
still binds, and a real uncovered regression vector exists: every E3-3 check in
`tests/backend/test_mc_model_routing.py` only inspects **repo-side** committed
assets (the profile/settings templates, the launch script, this doc,
`core/llm_client.py`) — **none inspects the pinned Mindcraft fork source**. So
the E3-6 ([#538](https://github.com/bradtaylorsf/livestreamtoagi/issues/538))
upstream-re-base flow could silently change Mindcraft's `Prompter` to ignore
`code_model` or collapse the chat/code tiers and **every E3-3 test stays
green** — exactly the *"an upstream rebase can't silently break the thesis"*
risk E3-7 names.

E3-7 closes that gap with **`tests/backend/test_mc_routing_fork_contract.py`**
(`pnpm verify:mindcraft-routing-contract`): a fork-**source** routing contract
asserting, against the pinned clone itself, that

- `src/models/prompter.js` still builds **separate** chat (`profile.model` →
  conversation tier) and code (`profile.code_model` → building tier) models,
  with the documented `code_model := chat_model` fallback intact;
- `src/models/_model_map.js` still dispatches the `lmstudio/` / `openrouter/`
  string prefixes to **distinct** provider classes;
- `src/models/openrouter.js` / `src/models/lmstudio.js` keep their
  `prefix`/`sendRequest` surface and the OpenRouter-has-no-embeddings caveat
  the word-overlap example fallback depends on (decision 0003);
- the zero-external-spend boundary holds as a *negative* contract (committed
  runtime profiles never carry `openrouter/`; providers never touch our DB),
  and per-agent `chat != code` still resolves through `core.llm_client`.

It mirrors the E3-3/E3-5 offline posture: the fork-source assertions
`skipif` when the disposable `./mindcraft` clone is absent (CI has no clone —
the suite stays green via the existing `backend-test` job, **no new CI
infra**), and run on any developer / E3-6 re-base host that has the clone —
regardless of which commit it sits at, since catching a re-based clone that
broke routing is the whole point. Every failure message points back at the
**E3-6 re-base runbook** (`docs/minecraft/fork-maintenance.md`, *"How to
re-base on upstream"*) and decision 0003's *"Evidence"* lines to re-review.

> **No LLM runtime path for #539.** This is a static fork-source contract — it
> never calls a model, so there is no LM Studio / OpenRouter step to validate
> for E3-7. The nearest local smoke is `pnpm verify:mindcraft-routing-contract`
> (clone present) or its skip-clean run (clone absent). Per-agent routing
> through LM Studio was validated in E3-3 ([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535)).

## The two verification bots

Two committed profile templates under `scripts/minecraft/profiles/`, each
routing a conversation `model` to a **different** building `code_model`:

| Bot | Profile | Mirrors | Conversation `model` | Building `code_model` |
|---|---|---|---|---|
| **RoutingBotA** | `routing-bot-a.json` | `agents/vera` | _A chat tier_ | _A code tier_ |
| **RoutingBotB** | `routing-bot-b.json` | `agents/aurora` | _B chat tier_ | _B code tier_ |

The two bots therefore exercise **four** routed models (2 bots × 2 tiers).

### Local validation (LM Studio — zero external spend, decision 0003)

The committed templates ship four **distinct substitution tokens**. The launch
script fills them from env (all four required for a real run):

| Bot | `model` (template) | `code_model` (template) | env vars |
|---|---|---|---|
| RoutingBotA | `lmstudio/__LLM_A_CHAT__` | `lmstudio/__LLM_A_CODE__` | `LLM_A_CHAT`, `LLM_A_CODE` |
| RoutingBotB | `lmstudio/__LLM_B_CHAT__` | `lmstudio/__LLM_B_CODE__` | `LLM_B_CHAT`, `LLM_B_CODE` |

A JSON comment is not valid JSON, so the production reference below is recorded
**here**, not in the profile files — the committed profiles are local-only
(`lmstudio/`), never `openrouter/`.

### Production reference (OpenRouter form — for later comparison only)

This is the production mapping the two verification bots **mirror**. It is kept
in lock-step with `agents/vera/config.yaml` / `agents/aurora/config.yaml` and
`core/llm_client.py` by `tests/backend/test_mc_model_routing.py` (the test fails
if any of them drift apart):

| Bot | Mirrors | Tier | Mindcraft string (`openrouter/…`) | `core/llm_client.py` alias → canonical | In `MODEL_REGISTRY` |
|---|---|---|---|---|---|
| RoutingBotA | `agents/vera` | `model` (chat) | `openrouter/anthropic/claude-haiku-4.5` | `anthropic/claude-haiku-4.5` → `claude-haiku-4-5` | ✅ |
| RoutingBotA | `agents/vera` | `code_model` (build) | `openrouter/anthropic/claude-sonnet-4.6` | `anthropic/claude-sonnet-4.6` → `claude-sonnet-4-6` | ✅ |
| RoutingBotB | `agents/aurora` | `model` (chat) | `openrouter/google/gemini-flash` | `google/gemini-flash` → `gemini-flash` | ✅ |
| RoutingBotB | `agents/aurora` | `code_model` (build) | `openrouter/google/gemini-2.5-pro` | `google/gemini-2.5-pro` → `gemini-2.5-pro` | ✅ |

The "alias → canonical" column is exactly
`core.llm_client.MODEL_NAME_ALIASES`; every canonical name is a key of
`core.llm_client.MODEL_REGISTRY`. Mindcraft's `openrouter/<provider>/<model>`
string with the `openrouter/` prefix stripped equals the
`MODEL_NAME_ALIASES` key, which mirrors what `OpenRouterClient._resolve_model`
does. **Preserve-no-regress:** these are the unchanged `model_conversation` /
`model_building` values from `agents/vera` and `agents/aurora`.

## How to run

### Static verify (no Node, no network, no clone)

```bash
pnpm mc:verify-routing
# shorthand for: scripts/minecraft/verify-model-routing.sh --verify
```

Asserts both committed profiles parse, each has `model != code_model`, both are
`lmstudio/`-only (no `openrouter/`), the two bot names differ, and the routing
settings template points at the E2 server with `log_all_prompts:true`.

The headless, dependency-free pytest equivalent (what CI runs):

```bash
pnpm verify:mindcraft-routing
# shorthand for: .venv/bin/pytest tests/backend/test_mc_model_routing.py -v
```

### Preview the resolved plan (no launch)

```bash
scripts/minecraft/verify-model-routing.sh --dry-run
```

### Real local run (LM Studio, two bots)

Prerequisites are the same as the E3-2 connect (`docs/minecraft/mindcraft-connect.md`):
E2 server running, the pinned fork installed (`scripts/minecraft/setup-mindcraft.sh`),
**Node 20 LTS**, and LM Studio serving on `http://localhost:1234/v1`.

```bash
pnpm llm:local --list-only          # confirm LM Studio + list served ids

# Pick at least two distinct ids so routing is observable:
export LLM_A_CHAT=<RoutingBotA conversation model id>
export LLM_A_CODE=<RoutingBotA building   model id>
export LLM_B_CHAT=<RoutingBotB conversation model id>
export LLM_B_CODE=<RoutingBotB building   model id>

scripts/minecraft/verify-model-routing.sh
```

The script stages `scripts/minecraft/mindcraft-settings-routing.js` →
`./mindcraft/settings.js` (host/port substituted, both routing profiles,
`log_all_prompts:true`), stages both profiles with the four ids substituted in,
applies the same launch-time runtime-version shim as `connect-stock-bot.sh`
(restored on exit), prints the **whitelist** commands for `RoutingBotA` /
`RoutingBotB`, then launches:

```text
cd ./mindcraft && node main.js --profiles ./profiles/routing-bot-a.json ./profiles/routing-bot-b.json
```

### Exercising both tiers

Join the E2 server with a normal Minecraft client and, in chat:

1. **Conversation tier** (hits each bot's `model`):
   `RoutingBotA hello, who are you?` and `RoutingBotB hello, who are you?`
2. **Building tier** (hits each bot's `code_model`):
   `RoutingBotA !newAction("place a block in front of you")` and
   `RoutingBotB !newAction("place a block in front of you")`

## Required LM Studio evidence checklist

Record the following in the issue/PR (no OpenRouter spend is required for
acceptance — decision 0003):

- [ ] **LM Studio reachable:** output of `pnpm llm:local --list-only`
      (or `.venv/bin/python scripts/check_local_llm.py --list-only`).
- [ ] **The four model ids used** for `LLM_A_CHAT`, `LLM_A_CODE`,
      `LLM_B_CHAT`, `LLM_B_CODE` (at least two distinct ids).
- [ ] **The exact command(s) run** (`scripts/minecraft/verify-model-routing.sh`,
      the two `whitelist add …` console commands).
- [ ] **Ran against the local Mac server** (E2 Paper on `127.0.0.1:25565`,
      `online-mode=false`).
- [ ] **Per-tier, per-bot proof:** for each bot, the chat request used
      `lmstudio/<chat id>` and the `!newAction` request used the **distinct**
      `lmstudio/<code id>`, shown by **either**:
      - LM Studio's **server request logs** (the model id per request), or
      - `./mindcraft/bots/RoutingBotA/logs` and
        `./mindcraft/bots/RoutingBotB/logs` (`log_all_prompts:true`).

> A real two-bot run needs Node 20 + a running E2 server + LM Studio. On a host
> without those, `pnpm verify:mindcraft-routing` / `pnpm mc:verify-routing` are
> the nearest local smoke paths and are what CI / the automated verifier runs.
> If no LLM runtime is available, state that explicitly and attach the
> static-verify output instead.

## Generating per-agent profiles (E3-4 / [#536](https://github.com/bradtaylorsf/livestreamtoagi/issues/536))

The two verification bots above are hand-written templates. The **production**
profiles are generated from the single source of truth
(`agents/<id>/config.yaml`) by `scripts/minecraft/gen_profiles.py`, so the
`openrouter/<provider>/<model>` strings can never be hand-copied out of sync
with `core/llm_client.py`:

```bash
# Production reference form (default) — openrouter/<config value> per tier,
# validated through core.llm_client.MODEL_NAME_ALIASES/MODEL_REGISTRY:
pnpm mc:gen-profiles vera
# shorthand for: .venv/bin/python scripts/minecraft/gen_profiles.py vera
# → {"name":"Vera","model":"openrouter/anthropic/claude-haiku-4.5",
#    "code_model":"openrouter/anthropic/claude-sonnet-4.6"}

# Local-dev / LM Studio form (zero external spend, decision 0003):
pnpm mc:gen-profiles vera --provider lmstudio --local-chat <id> --local-code <id>
# (env fallback: LOCAL_LLM_MODEL / LOCAL_LLM_MODEL_BUILDING)

# Write to a profile file instead of stdout:
pnpm mc:gen-profiles vera --out ./mindcraft/profiles/vera.json
```

The emitted schema is exactly `{name, model, code_model}` — the same minimal
shape as the committed sibling templates (`stock-bot.json`,
`routing-bot-a.json`). **Management is refused** (a content filter, never a
world bot — E7-5); **Alpha generates** (its non-verbal/no-chat behavior is an
E7-1 runtime concern, not a profile field). Mapping *all nine* agents at launch
is **E8**; this generator emits one profile per call.

The headless, dependency-free pytest equivalent (what CI runs):

```bash
pnpm verify:mindcraft-profiles
# shorthand for: .venv/bin/pytest tests/backend/test_mc_profile_gen.py -v
```

> This generator has **no LLM runtime path** — it only emits JSON. The nearest
> local smoke is `pnpm verify:mindcraft-profiles` plus the
> `--provider lmstudio` form above (no OpenRouter spend required for
> acceptance).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `✗ Missing required model id(s): …` | One or more of the four `LLM_*` env vars unset. | Export all four (`pnpm llm:local --list-only` to list ids). |
| Both bots answer with the same model id | Same id exported for several `LLM_*` vars. | Use at least two distinct LM Studio ids. The script prints a non-fatal `⚠` when a bot's `chat == code` id (that tier split is unobservable) and a louder one when *all four* ids are identical (vacuous demo). |
| `✗ LM Studio not reachable` | LM Studio not serving on `http://localhost:1234/v1`. | Start LM Studio there (its default); `pnpm llm:local --list-only` to confirm. Overriding `LOCAL_LLM_BASE_URL` only moves the *pre-flight* check, not the bots (string-form `lmstudio/` profiles always use the built-in endpoint at the pinned commit — same as E3-2). |
| `✗ No Mindcraft clone at ./mindcraft` / `not at the pinned commit` | Fork not installed / drifted. | `scripts/minecraft/setup-mindcraft.sh` (see `docs/minecraft/mindcraft-fork.md`). |
| `✗ Node 22 found, but the pinned Mindcraft needs Node 20 LTS` | Wrong Node major. | `nvm install 20 && nvm use 20`. |
| Bots kicked instantly (`not white-listed`) | E2 `white-list=true`, names not added. | `whitelist add RoutingBotA` **and** `whitelist add RoutingBotB` in the E2 console, or restart E2 with `WHITELIST=false`. |
| `✗ Mindcraft source shape changed; cannot apply runtime-version shim` | The pinned fork changed `src/utils/mcdata.js`. | Re-run `setup-mindcraft.sh`; re-review the pinned fork before launching. |
| Prompt logs missing under `./mindcraft/bots/<name>/logs` | A non-routing `settings.js` was staged. | Re-run `scripts/minecraft/verify-model-routing.sh` (it stages `mindcraft-settings-routing.js`, which sets `log_all_prompts:true`). |

## Where this is recorded

- **`docs/decisions/0003-mindcraft-model-routing.md`** — the decision this
  issue verifies (`model` vs `code_model`, LM Studio/OpenRouter string syntax,
  no fork patch needed for basic routing). Back-references E3-3/#535.
- **`docs/minecraft/mindcraft-connect.md`** — the E3-2 stock-bot connect this
  builds on (links here under *Related*).
- **`core/llm_client.py`** — `MODEL_NAME_ALIASES` / `MODEL_REGISTRY`, the
  canonical source the production reference mapping mirrors.
- **`tests/backend/test_mc_model_routing.py`** — the headless contract test
  that keeps the profiles, the doc, the agent configs, and `core/llm_client.py`
  in lock-step.
- **`tests/backend/test_mc_routing_fork_contract.py`** — the E3-7
  ([#539](https://github.com/bradtaylorsf/livestreamtoagi/issues/539))
  fork-**source** routing contract (`pnpm verify:mindcraft-routing-contract`):
  asserts the pinned Mindcraft fork still routes `model`/`code_model` to
  separate, distinct providers so an E3-6 upstream re-base cannot silently
  break the thesis. Skips clean when no clone is present.
- **`docs/minecraft/fork-maintenance.md`** — the E3-6
  ([#538](https://github.com/bradtaylorsf/livestreamtoagi/issues/538))
  upstream-re-base runbook the E3-7 contract protects (every fork-source
  failure points back at its *"How to re-base on upstream"* section).
- **`scripts/minecraft/gen_profiles.py`** / **`tests/backend/test_mc_profile_gen.py`**
  — the E3-4 ([#536](https://github.com/bradtaylorsf/livestreamtoagi/issues/536))
  generator that emits per-agent profiles from `agents/<id>/config.yaml`
  (`pnpm mc:gen-profiles` / `pnpm verify:mindcraft-profiles`).

### Related

- **`docs/minecraft/mindcraft-stripped-features.md`** — the E3-5
  ([#537](https://github.com/bradtaylorsf/livestreamtoagi/issues/537)) sibling:
  disables the Python-superseded Mindcraft features (memory/examples/voice/
  vision per decision 0003) behind reversible `settings.js` flags, while
  **keeping** the decentralized conversation (decision 0004). Same
  committed-artifact + staged-into-clone pattern as this runbook.
