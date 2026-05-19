# Curated Minecraft Skill Set (E6-1)

This is the E6-1 deliverable for [#556](https://github.com/bradtaylorsf/livestreamtoagi/issues/556):
define the deliberate Minecraft action/skill surface before implementation.
Mindcraft ships many commands; the pivot keeps only the skills that support
real movement, building, perception, and verified outcomes.

> **Issue:** E6-1 (epic E6, [#556](https://github.com/bradtaylorsf/livestreamtoagi/issues/556)).
> **Plan:** [`docs/MINECRAFT-PIVOT-ISSUE-PLAN.md`](../MINECRAFT-PIVOT-ISSUE-PLAN.md) section 5, Epic 6.
> **Decisions bound:** [`docs/decisions/0004-decentralized-conversation.md`](../decisions/0004-decentralized-conversation.md)
> and [`docs/decisions/0005-skill-extension-point.md`](../decisions/0005-skill-extension-point.md).
> **Related contracts:** [`docs/minecraft/bridge-contract.md`](bridge-contract.md)
> and [`docs/minecraft/mindcraft-stripped-features.md`](mindcraft-stripped-features.md).
> **Scope:** In = enumerate allowed skills, excluded skills, inputs, and
> verification signals. Out = implement the skills; E6-2 through E6-6 do that.

## Allowed Skills

Decision 0005 fixes the fork-level extension points: explicit actions in
`src/agent/commands/actions.js`, queries in `src/agent/commands/queries.js`,
and generated-code-callable helpers in `src/agent/library/skills.js` only when
safe. This table is the closed allowed surface for the E6 action layer.

| Skill | Mindcraft extension point | Inputs (typed args) | Verification signal | Implementing issue |
| --- | --- | --- | --- | --- |
| `move` | Action in `src/agent/commands/actions.js`; optional safe helper in `src/agent/library/skills.js` for generated build code. | `{ action_id: string, direction: "forward" \| "back" \| "left" \| "right" \| "up" \| "down" \| "north" \| "south" \| "east" \| "west", distance_blocks: number, timeout_ms?: number }` | Bot reports terminal `action.result` status and Python confirms the post-move pose delta with a follow-up perception read. Success means the measured pose changed by the requested relative distance within tolerance; failure names blocked, invalid, timed-out, or bridge-down. | E6-2 / [#557](https://github.com/bradtaylorsf/livestreamtoagi/issues/557) |
| `navigate` | Action in `src/agent/commands/actions.js`; optional safe helper in `src/agent/library/skills.js` for generated build code. | `{ action_id: string, target: { x: number, y: number, z: number } \| { block: string, nearest?: boolean } \| { entity_id: string }, arrive_within_blocks?: number, timeout_ms: number }` | Bot reports `action.result` as reached-target, blocked, unreachable, timed-out, invalid, or bridge-down. Python verifies success by comparing the final pose from `perception.report` with the target/tolerance. | E6-2 / [#557](https://github.com/bradtaylorsf/livestreamtoagi/issues/557) |
| `place` | Action in `src/agent/commands/actions.js`; safe helper in `src/agent/library/skills.js` for build plans. | `{ action_id: string, block_type: string, position: { x: number, y: number, z: number }, face?: "top" \| "bottom" \| "north" \| "south" \| "east" \| "west", source_slot?: number }` | Verified only when a post-action world read confirms `block_type` is present at `position`. `action.result` must not mark success just because the place command was issued. Inventory delta may be included as secondary evidence. | E6-3 / [#558](https://github.com/bradtaylorsf/livestreamtoagi/issues/558) |
| `break` | Action in `src/agent/commands/actions.js`; safe helper in `src/agent/library/skills.js` for build plans. | `{ action_id: string, position: { x: number, y: number, z: number }, expected_block_type?: string, tool_slot?: number }` | Verified only when a post-action world read confirms the target block is absent or replaced by the expected residual state. `action.result` distinguishes success from blocked, protected, invalid, timed-out, or tool-missing outcomes. | E6-3 / [#558](https://github.com/bradtaylorsf/livestreamtoagi/issues/558) |
| `craft` | Action in `src/agent/commands/actions.js`; safe helper in `src/agent/library/skills.js` only for explicit recipes/items. | `{ action_id: string, item_id: string, count: number, recipe_id?: string, station?: "inventory" \| "crafting_table" \| "furnace" }` | Bot reports `action.result`; Python verifies with an inventory snapshot showing the requested output count increased and required inputs decreased or remained consistent with recipe rules. | Later embodiment/backlog issue after E6-3, unless pulled into E6-4 for build-plan dependencies. |
| `inventory` | Read-only helper used by `!observe`; a separate query command may be added later if needed. | `{ filter?: { item_id?: string, tag?: string, slot?: number }, include_equipment?: boolean }` | Verification is the returned schema-valid inventory snapshot, optionally filtered, including counts, slots, and equipment. This is read-only; it reports `perception.report`/query data rather than changing the world. | E6-6 / [#561](https://github.com/bradtaylorsf/livestreamtoagi/issues/561) |
| `build-from-plan` | Code-generation skill in `src/agent/library/skills.js` backed by the safe `place`, `break`, `navigate`, `craft`, and `inventory` primitives; no arbitrary bridge verbs. | `{ action_id: string, origin: { x: number, y: number, z: number }, plan: { blocks: Array<{ dx: number, dy: number, dz: number, block_type: string }>, palette?: Record<string, string>, clear?: Array<{ dx: number, dy: number, dz: number }> }, max_steps?: number, timeout_ms?: number }` | Verified by per-step `action.result` records plus an actual-vs-intended completion metric from a final perception/world read: intended blocks present, unexpected blocks, missing blocks, and abandoned steps. | E6-4 / [#559](https://github.com/bradtaylorsf/livestreamtoagi/issues/559) |
| `observe` / `perception` | Read-only action `!observe` in `src/agent/commands/actions.js`; emits `perception.report` from the Node side. | `{ radius_blocks?: number, scope?: "pose" \| "nearby_blocks" \| "entities" \| "inventory" \| "all", include_air?: boolean }` | Verification is a schema-valid perception snapshot containing the requested pose, nearby blocks, entities, inventory, and relevant metadata. This is the source used to verify action results. | E6-6 / [#561](https://github.com/bradtaylorsf/livestreamtoagi/issues/561) |

E6-4 implements `build-from-plan` as a staged action command,
`!buildFromPlan`, rather than editing `src/agent/library/skills.js`. That keeps
it aligned with the verified action triad from E6-2/E6-3: pure helper module,
Node action command, Python verifier, and bridge-script staging/injection.
There is no new LLM runtime path for this skill; it consumes an already
structured plan and verifies observed block outcomes.

Code-writing is retained as a separate tool through the existing bridge/sandbox
path, tracked by E6-5 ([#560](https://github.com/bradtaylorsf/livestreamtoagi/issues/560)).
It is not removed and it is not a substitute for the closed in-world action set
above.

E6-6 implements `observe` as a staged read-only Mindcraft action, `!observe`,
plus a pure `perception.js` helper. The action emits one `perception.report`
containing a typed `PerceptionSnapshot` (`pose`, `nearby_blocks`, `entities`,
`inventory`, `radius_blocks`, `scope`, `include_air`, and `captured_tick`) and
does not emit `action.result`.

## Verification Signal Model

Every mutating action skill must return a verified outcome over the bridge,
using the existing [`action.result`](bridge-contract.md#closed-service-set)
verb for the terminal result and the
[`perception.report`](bridge-contract.md#closed-service-set) verb or perception
query for the post-action read.

"Verified" means the real world or inventory was observed after the attempted
action and the observation confirms the outcome. It does not mean only that the
Mindcraft command was accepted, queued, or attempted. The Python side should be
able to answer: what changed, what did not change, and which failure class
applies.

Expected terminal classes are intentionally small until E6-7 formalizes them:

| Class | Meaning | E6-7 direction |
| --- | --- | --- |
| `success` | The post-action read confirms the intended world/inventory/pose state. | Record and continue. |
| `partial` | Some steps or deltas verified, but not the whole requested outcome. | Return detailed progress; caller may retry bounded or abandon. |
| `blocked` | Physical obstruction, protected block, missing reachability, or missing required item/tool prevented completion. | Safe-idle or retry bounded based on action type. |
| `timed-out` | The action did not reach a terminal verified state before `timeout_ms`. | Retry bounded or abandon. |
| `invalid` | Input failed schema, range, whitelist, recipe, or target validation. | Abandon; do not retry unchanged. |
| `unreachable` | Pathfinding cannot reach the target or required interaction point. | Abandon or request a new plan. |
| `bridge-down` | The bridge is disconnected or overloaded. | Safe-idle; never perform unverified or ungated action. |

The exact failure taxonomy and safe behavior tests are E6-7
([#562](https://github.com/bradtaylorsf/livestreamtoagi/issues/562)). This
document only fixes the skill surface and the requirement that success is
confirmed by observation.

## Excluded Skills

These exclusions are scope/config-level decisions, not irreversible fork-core
deletions. The same reversible posture as
[`mindcraft-stripped-features.md`](mindcraft-stripped-features.md) applies: a
future issue may intentionally re-enable or replace one, but E6 does not treat
it as part of the curated action layer.

| Skill/category | Why excluded | Superseded by / cross-reference |
| --- | --- | --- |
| Mindcraft self-conversation-as-skill commands outside the retained decentralized conversation base | Conversation is not part of the action-success surface. Decision 0004 keeps Mindcraft's decentralized conversation as the base, but E6 does not add extra conversation commands as skills. | [`docs/decisions/0004-decentralized-conversation.md`](../decisions/0004-decentralized-conversation.md); E8 owns personality/proximity/eavesdrop behavior. |
| Persona/base-profile prompting as a skill | Agent identity is not an in-world action and should not be mutated by the Minecraft action layer. The residual Mindcraft base profile gap is documented, not solved in E6. | [`mindcraft-stripped-features.md`](mindcraft-stripped-features.md), decision 0003, and later E8 profile/bridge work. |
| Mindcraft session memory and retrieval skills | Python owns memory and context. Running Mindcraft memory/retrieval in parallel creates a second source of truth and token cost. | [`mindcraft-stripped-features.md`](mindcraft-stripped-features.md); E5 memory bridge. |
| TTS/voice skills | Voice is a Python-side stream/TTS concern, not an in-world action. | [`mindcraft-stripped-features.md`](mindcraft-stripped-features.md) and the Python Edge TTS pipeline. |
| Mindcraft vision tier | The pivot uses explicit perception snapshots instead of a general vision tier for this action layer. | [`mindcraft-stripped-features.md`](mindcraft-stripped-features.md); E6-6 perception API. |
| Generic `!newAction`, arbitrary-code action creation, or "execute arbitrary Python" | Decision 0005 requires a closed verb set. Generated code may call only explicitly safe skills; the bridge must not expose arbitrary Python execution. | [`docs/decisions/0005-skill-extension-point.md`](../decisions/0005-skill-extension-point.md); E6-5 keeps code execution via the existing sandbox path, not as arbitrary bridge verbs. |
| Combat, PvP, attack, and griefing/destructive-at-scale actions | Off-mission for "build/create with verification" and unsafe for a 24/7 public show. Destructive primitives are limited to verified `break` for scoped build plans or explicit repairs. | Product safety posture; E6-3 verified block breaking only. |
| Cross-server, teleport, operator-only, or permission-escalating commands | They bypass embodied movement/building and do not provide meaningful action-success verification in the normal world. | E6-2 navigation and E6-6 perception; server administration remains outside agent skills. |
| Chat/social actions owned by the Python brain | The livestream social layer, Management review, cost gates, and audience-facing chat policy are not Mindcraft action skills. | Decisions 0004/0005, Management review bridge hooks, and later E8 social behavior. |

## LM Studio Validation

E6-6 has no LLM runtime path: it adds schema/data plumbing and a read-only
Mindcraft perception action, but no model call. Per the local-validation
policy, confirm LM Studio reachability and run the nearest local smoke path.

The nearest local smoke path is the perception verifier, which exercises the
committed `!observe` action with a fake bot and validates the resulting bridge
snapshot without a live server:

```bash
pnpm llm:local --list-only
pnpm verify:embodiment-perception
```

For a real local Minecraft run, follow
[`docs/minecraft/mindcraft-stripped-features.md`](mindcraft-stripped-features.md#real-local-run-lm-studio--zero-external-spend-decision-0003)
and use LM Studio/OpenAI-compatible local model ids in the generated profiles.
Record the LM Studio model id(s), commands run, and whether the validation ran
against the local Mac server. If LM Studio or the E2 server is not available,
state that and attach the static perception verification output instead.
