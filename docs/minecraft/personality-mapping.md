# Mindcraft Personality Mapping

Issue: #576 / E8-5
Decision basis: [0004: Decentralized Conversation](../decisions/0004-decentralized-conversation.md)

## Summary

Mindcraft's native decentralized conversation hook is the profile-level
`bot_responder` prompt, which returns `respond` or `ignore`. The generated
profiles now also carry a `personality` block with deterministic probabilities
derived from `agents/<id>/config.yaml`. The fork conversation layer can read
those numeric fields without re-parsing YAML.

`name`, `model`, and `code_model` remain the required Mindcraft routing keys.
`bot_responder` and `personality` are additive E8 metadata.

Run-spec persona overrides are applied only at generation time. Passing
`--run-spec <path>` to `scripts/minecraft/gen_profiles.py` reads the
`persona_overrides` block and adds `backstory` plus a compact `persona` block
to only the affected profile JSON files. The committed `agents/<id>/` files
are not edited, and profiles without overrides keep the baseline schema.

## Mapping

| Agent config knob | Generated profile surface | Formula / value |
| --- | --- | --- |
| `chattiness` | `personality.respond_probability` | `clamp(0.15 + 0.7 * chattiness + 0.15 * interrupt_tendency, 0, 1)` |
| `chattiness` + `initiative` | `personality.initiate_probability` | `clamp(0.05 + 0.7 * chattiness * (0.5 + 0.5 * initiative), 0, 1)` |
| `interrupt_tendency` | `personality.interrupt_bias` and `bot_responder` wording | Mirrors `interrupt_tendency`; the prompt only encourages busy-state override when this value is high. |
| `eavesdrop_tendency` | `personality.eavesdrop_probability` | Mirrors `eavesdrop_tendency`. |
| `adjacency` | `personality.adjacency` | Raw `agent_id -> weight` map from config, JSON-normalized to strings and numbers. |
| `closing_weight` | `personality.closing_weight` | Preserved for downstream cadence/ending policy; no native Mindcraft field. |
| `role_priority_bonus` | `personality.role_priority_bonus` | Preserved for downstream priority policy; no native Mindcraft field. |

Special case: `alpha` is action-only, so generated profiles set
`personality.respond_probability = 0` and
`personality.initiate_probability = 0`. Its `bot_responder` prompt returns
`ignore` for normal conversation.

## Measurable Rates

The mapping preserves the intended ordering from config:

| Pair | Chattiness | Respond probability | Initiate probability |
| --- | ---: | ---: | ---: |
| Grok > Sentinel | `0.8 > 0.6` | `0.83 > 0.675` | `0.498 > 0.344` |
| Pixel > Fork | `0.9 > 0.5` | `0.855 > 0.59` | `0.5855 > 0.2775` |

These rates are verified in
`tests/backend/test_mc_personality_mapping.py` without Minecraft or LLM calls.

## Gaps

Mindcraft at the pinned decision commit does not natively expose every old
Python conversation knob:

| Gap | Current status | Follow-up owner |
| --- | --- | --- |
| Numeric chattiness / initiative enforcement | Profiles expose probabilities, but the fork still needs to use them when choosing whether to start `!startConversation`. | E8-6 conversation-layer work |
| Full initiative cadence | `initiate_probability` is available in the profile, but scheduling cadence still depends on bridge/Python state such as energy and current goals. | E8-6 / bridge integration |
| Eavesdropping | `eavesdrop_probability` is config-only until bot-to-bot transcript broadcast or nearby overhear exists. | E8-6 or later proximity/eavesdrop patch |
| Adjacency / peer selection | `adjacency` is preserved, but Mindcraft does not natively choose peers by this map or by proximity. | E8-6 conversation-layer work |
| Closing behavior | `closing_weight` is preserved only; native Mindcraft pairwise conversation has no matching field. | Later cadence/end-policy work |
| Role priority | `role_priority_bonus` is preserved only; native Mindcraft has no equivalent priority bonus. | Later priority policy work |

## Local Validation

The generator has no direct LLM runtime path; it emits local-only LM Studio
profile templates. Validate the nearest local path with:

```bash
pnpm llm:local --list-only
pnpm mc:gen-profiles --all --provider lmstudio --local-chat <model-id> \
  --run-spec tests/backend/fixtures/scenarios/with_run_spec.yaml --out /tmp/profiles
pnpm verify:mindcraft-profiles
```

Do not use bare `python` for this validation. This repo intentionally routes
Python commands through `pnpm` scripts or `.venv/bin/python` so stale PATH shims
cannot point at another worktree.

For real bot validation, use the committed `lmstudio/__LOCAL_LLM_MODEL__`
templates and the existing `connect-*-bot.sh` launchers so profiles resolve to
local LM Studio model IDs instead of `openrouter/...`.
