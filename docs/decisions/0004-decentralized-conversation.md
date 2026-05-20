# Decision 0004: Decentralized Conversation

Status: accepted for coding, with known gaps

Research date: 2026-05-18

Related issue: #521, E1-R4

## Non-Technical Summary

Mindcraft does have decentralized bot-to-bot conversation, but it is narrower
than the original epic implied. It is not a room where every bot hears every
message and freely decides whether to speak. It is a pairwise conversation
system: one bot starts a conversation with another bot, messages are routed by
MindServer, and the receiving bot may delay, respond, or sometimes ignore while
busy.

This is still good enough to replace the Python central speaker director for the
Minecraft pivot, but we need to patch or extend it for eavesdropping, proximity,
and personality-calibrated initiation.

## Decision

- Use Mindcraft's bot-to-bot conversation as the base, not the old Python
  `ConversationEngine` as a speaker director.
- Keep Python as the source of truth for personality knobs, memory, energy,
  Management review, and cost controls.
- Add a thin personality/proximity layer in the Mindcraft fork after the bridge
  exists.
- Treat eavesdropping and group chat as explicit new work, not native Mindcraft
  behavior.

## Implementation: E8-6 Gate

Embodied runs set `CONVERSATION_MODE=embodied`. The default remains
`CONVERSATION_MODE=director` so legacy simulations still use the Python
conversation director.

The gate is applied at the two Python callsites that construct the director:

- `core/simulation/phases.py::_run_conversation`
- `core/main.py::dev_simulate`

This flag does not delete `core/conversation_engine.py` or
`core/conversation/speaker_selector.py`; that removal is reserved for E14-era
cleanup after the embodied path is stable.

> **Verified by E3-5 ([#537](https://github.com/bradtaylorsf/livestreamtoagi/issues/537)).**
> When E3-5 stripped the Python-superseded Mindcraft features, the
> decentralized bot-to-bot conversation was **deliberately KEPT**:
> `chat_bot_messages` stays `true` and the conversation system is not disabled.
> The contract test asserts it is not stripped — see
> `docs/minecraft/mindcraft-stripped-features.md`,
> `scripts/minecraft/mindcraft-settings-stripped.js`, and
> `tests/backend/test_mc_stripped_features.py`. The personality/proximity/
> eavesdrop layer remains E8 new work (not removal).

## What Mindcraft Actually Does

Mindcraft exposes `!startConversation(player_name, message)` and
`!endConversation(player_name)` actions. The message goes through MindServer's
Socket.IO `chat-message` event to the target bot process. Each bot has at most
one active conversation. If a bot is already in a different conversation, it
rejects the new one.

Response timing is state-based:

- Neither bot busy: respond quickly.
- Other bot busy: wait longer.
- Receiving bot busy: allow fast response for some actions, otherwise ask the
  LLM whether to respond.
- Both busy: usually wait/ignore unless the current action can be talked over.

The LLM "respond or ignore" check is a profile prompt named `bot_responder` and
expects the exact result `respond` to return true.

Open chat from humans is handled separately. If more than one bot is connected,
Mindcraft ignores public chat messages and uses the bot-to-bot channel instead.

## Mapping From Existing Agent Knobs

| Current config knob | Mindcraft mapping | Gap |
| --- | --- | --- |
| `chattiness` | Probability/threshold for initiating `!startConversation` while idle or after events. | Needs our layer. Native Mindcraft does not expose a numeric chattiness knob. |
| `initiative` | Self-prompt cadence and proactive goal/conversation scheduling. | Needs our layer. |
| `interrupt_tendency` | Bias `bot_responder` and busy-state response decisions. | Needs prompt/config patch. |
| `eavesdrop_tendency` | Whether a bot sees/records other bots' conversations. | Not native. Needs transcript broadcast or nearby overhear patch. |
| proximity groups | Use Mineflayer positions and nearby bot players before starting/overhearing conversations. | Not native. Needs bridge/Mindcraft logic. |
| energy | Python-owned. Should affect initiation and interruption through bridge state. | Needs E4/E8. |
| Management | Out-of-band review before output broadcast. | Needs bridge hook in `routeResponse`/`openChat`. |

## Special Agents

- `management`: never spawned as a bot. It remains a Python-side review service.
- `alpha`: spawned first for the vertical slice, but should not initiate or
  participate in normal chat. Its generated profile should block
  `!startConversation` and use action-only prompts.

## Implementation Implications

- E8 should not try to port the whole Python conversation director.
- E8 should implement a decentralized initiation policy:
  `agent state + proximity + chattiness + initiative + current goal -> maybe
  start conversation`.
- E8 should implement an eavesdrop mechanism if we want Pixel/Grok-style social
  behavior. The simplest version is a MindServer broadcast of bot-to-bot
  messages plus a per-agent filter.
- E4 should provide bridge state reads so Mindcraft can ask Python for energy,
  relationships, recent memory, and Management review.

## Evidence

- Mindcraft conversation manager:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/conversation.js#L121-L195
- Mindcraft response scheduling and busy/ignore logic:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/conversation.js#L261-L307
- Mindcraft `bot_responder` prompt call:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/models/prompter.js#L293-L301
- Mindcraft bot conversation commands:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/commands/actions.js#L407-L435
- MindServer routes bot-to-bot chat:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/mindcraft/mindserver.js#L200-L207
- Mindcraft ignores public chat when multiple agents exist:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/agent.js#L184-L188
