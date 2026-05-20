# Alpha Mindcraft Profile (E7-1)

Alpha is the first E7 vertical-slice bot: one embodied, non-verbal helper wolf
in the E2 Minecraft world. Its identity and model tiers remain sourced from
`agents/alpha/config.yaml` and `agents/alpha/system_prompt.md`; this page covers
only the Mindcraft profile and launch settings.

## Contract

- Bot username: `Alpha`.
- Profile: `scripts/minecraft/profiles/alpha-bot.json`.
- Settings: `scripts/minecraft/mindcraft-settings-alpha.js`.
- Launch command: `pnpm mc:connect-alpha` or
  `scripts/minecraft/connect-alpha-bot.sh`.
- E2 target: local Mac server at `127.0.0.1:25565`, `auth: "offline"`,
  `minecraft_version: "1.21.6"`.
- Model routing: `model` and `code_model` are local LM Studio ids:
  `lmstudio/<LOCAL_LLM_MODEL>` and
  `lmstudio/<LOCAL_LLM_MODEL_BUILDING>`.

Alpha must not emit chat. The launch settings enforce that with:

| Setting | Alpha value | Purpose |
|---|---:|---|
| `chat_ingame` | `false` | Suppress LLM responses in Minecraft chat. |
| `narrate_behavior` | `false` | Suppress automatic action narration. |
| `chat_bot_messages` | `false` | Prevent public bot-to-bot messages. |
| `init_message` | `""` | Avoid spawn-time chat. |
| `speak` | `false` | Keep Alpha voiceless. |
| `only_chat_with` | `[]` | No chat allow-list; chat output is disabled. |

The system prompt still limits Alpha's symbolic vocabulary (alert, question,
happy, success, failure symbols). E7-1 is stricter at the Mindcraft layer:
Alpha should act, not chat.

## Local LM Studio Validation

Confirm LM Studio is reachable and record the served model id:

```bash
pnpm llm:local --list-only
```

Then run the headless verification:

```bash
pnpm verify:mindcraft-alpha
scripts/minecraft/connect-alpha-bot.sh --verify
scripts/minecraft/connect-alpha-bot.sh --dry-run
```

For a real local Mac server run:

```bash
export MINECRAFT_BRIDGE_TOKEN=<same-secret-as-fastapi>
export LOCAL_LLM_MODEL=<model-id-from-LM-Studio>
export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>  # optional
pnpm mc:connect-alpha
```

Record in the issue or PR:

- LM Studio model id used for `LOCAL_LLM_MODEL`.
- `LOCAL_LLM_MODEL_BUILDING`, if set.
- The commands run.
- Whether validation ran against the local Mac server at `127.0.0.1:25565`.
- Whether Alpha joined as `Alpha` and emitted no chat.

If the Minecraft server, Node 20, or LM Studio is unavailable, use
`pnpm verify:mindcraft-alpha` as the nearest local smoke path and state that no
real Mindcraft launch was run on that host.
