# Decision 0003: Mindcraft Model Routing

Status: accepted for coding

Research date: 2026-05-18

Related issue: #520, E1-R3

## Non-Technical Summary

Mindcraft now supports the core model-routing idea well enough to begin coding.
Each bot profile can name one model for conversation and a different model for
code/building actions. LM Studio and OpenRouter are both native supported
providers.

We do not need an immediate fork patch just to route chat vs building models.
We will still need local glue to generate Mindcraft profiles from our existing
`agents/<id>/config.yaml` files, and we should not rely on Mindcraft for cost
tracking or memory.

## Decision

- Use Mindcraft profile `model` for the conversation tier.
- Use Mindcraft profile `code_model` for the building/code tier.
- Use LM Studio string syntax for local validation profiles:
  `lmstudio/<model-id-from-LM-Studio>`.
- Keep OpenRouter string syntax available for later production/comparison
  profiles: `openrouter/<provider>/<model>`.
- Generate Mindcraft profiles from `agents/<id>/config.yaml`, using:
  - `model_conversation` -> Mindcraft `model`
  - `model_building` -> Mindcraft `code_model`
- Do not spawn `management` as a Mindcraft bot.
- Spawn `alpha` first, but with chat initiation disabled and action-only prompts.
- Use a non-OpenRouter embedding provider for Mindcraft's own example-selection
  feature, or disable/de-emphasize Mindcraft examples until E5 replaces this
  with the Python memory service.

## Important Caveats

Mindcraft's OpenRouter class does not implement embeddings. Local validation
should prefer LM Studio embeddings when the loaded model supports them, or fall
back to word-overlap during skill doc selection. That is acceptable for the
first vertical slice, but profile generation should set an explicit embedding
provider later if we keep Mindcraft examples enabled.

Mindcraft's model providers do not track cost in our database. OpenRouter also
does not currently pass arbitrary `params` through in the constructor. Cost
controls remain Python-side work in E4/E11, and local LM Studio validation should
record zero external model spend.

## Example Generated Profile Shape

```json
{
  "name": "vera",
  "model": "lmstudio/<conversation-model-id>",
  "code_model": "lmstudio/<building-model-id>",
  "embedding": "lmstudio/<embedding-model-id>"
}
```

If LM Studio is not serving an embedding model during the first local slice,
omit `embedding` and accept word-overlap skill selection until the Python bridge
takes over memory/example retrieval.

## Agent Model Mapping

| Agent | Local validation `model` | Local validation `code_model` |
| --- | --- | --- |
| vera | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| rex | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| aurora | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| pixel | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| fork | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| sentinel | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| grok | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| alpha | `lmstudio/<conversation-model-id>` | `lmstudio/<building-model-id>` |
| management | do not spawn | do not spawn |

## Patch Scope

No fork patch is required for basic per-agent/per-tier routing through LM
Studio or OpenRouter.

> **Verified by E3-3 ([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535)).**
> Two bots (`RoutingBotA`/`RoutingBotB`) each route a conversation `model` to a
> distinct building `code_model` with **no fork patch** — see
> `docs/minecraft/model-routing.md` and `tests/backend/test_mc_model_routing.py`.

Patches still expected later:

- Cost-gated wrapper before model calls or bridge-level cost accounting.
- Management review before bot output is broadcast.
- Optional profile `params` support for OpenRouter calls if we need model-level
  temperature/max-token settings.
- Profile generator in this repo.

## Evidence

- Mindcraft lists OpenRouter as a supported API:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/README.md#L59-L78
- Mindcraft profile model syntax and tier docs:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/README.md#L170-L218
- Mindcraft dynamic API selection:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/_model_map.js#L33-L88
- Mindcraft OpenRouter implementation:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/openrouter.js#L5-L76
- Mindcraft LM Studio implementation:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/lmstudio.js#L5-L62
- Mindcraft `Prompter` creates separate chat/code/vision models:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/prompter.js#L59-L76
- Mindcraft uses `code_model` for coding:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/prompter.js#L264-L278
- OpenRouter request support issue #493 is closed with maintainer comment that
  OpenRouter is already supported:
  https://github.com/mindcraft-bots/mindcraft/issues/493
