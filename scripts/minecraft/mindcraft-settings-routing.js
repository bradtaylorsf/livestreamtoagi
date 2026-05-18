// ─────────────────────────────────────────────────────────────────────────────
// Committed Mindcraft settings template — TWO bots, distinct per-tier models.
//
// This is the reviewed `settings.js` referenced by docs/minecraft/model-routing.md
// (issue #535, epic E3-3). It proves per-agent multi-model routing: two bots
// with different profiles each route a conversation-tier `model` and a distinct
// building-tier `code_model` to LM Studio (decision 0003 — native routing, no
// fork patch). `./mindcraft` is git-ignored, so the ONLY committed artifacts are
// this template + the two routing profiles; scripts/minecraft/verify-model-routing.sh
// stages them into the clone before launch (same committed-artifact pattern as
// connect-stock-bot.sh / E3-2).
//
// It is a faithful copy of scripts/minecraft/mindcraft-settings.js (the reviewed
// E3-2 stock-bot template, itself a faithful copy of pinned upstream
//   mindcraft-bots/mindcraft@35be480b4cc0bca990278e6103a1426392559d96/settings.js)
// with ONLY the two deltas this issue needs changed (every change is flagged
// "E3-3:" inline). Keeping every other key verbatim means Mindcraft never reads
// an undefined setting and the E3-2 E2-server contract is preserved unchanged.
//
// What changed vs. the E3-2 stock-bot template, and why:
//   - profiles -> ["./profiles/routing-bot-a.json", "./profiles/routing-bot-b.json"]
//     (TWO bots so we can demonstrate two profiles hitting different models;
//     our nine production agents are E8, explicitly NOT this issue)
//   - log_all_prompts false -> true  (per-bot prompt logs under
//     ./mindcraft/bots/<name>/logs are the evidence proving which LM Studio
//     model id served chat vs code for each bot)
//
// Everything else (host/port/auth/minecraft_version/auto_open_ui/…) is the
// reviewed E3-2 template verbatim, and host/port/profiles are env-overridable by
// the launch script — see verify-model-routing.sh --help.
// ─────────────────────────────────────────────────────────────────────────────
const settings = {
    "minecraft_version": "1.21.6", // E3-2: pinned to the E2 Paper version (E1-R1 / decisions 0001), was "auto"
    "host": "127.0.0.1", // E1-R2: localhost only — offline-mode bots must not be public (decisions 0002)
    "port": 25565, // E3-2: E2 server default (start-server.sh leaves server-port unset), was 55916
    "auth": "offline", // E1-R2: matches Paper online-mode=false (decisions 0002)

    // the mindserver manages all agents and hosts the UI
    "mindserver_port": 8080,
    "auto_open_ui": false, // E3-2: headless connect — no browser UI, was true

    "base_profile": "assistant", // survival, assistant, creative, or god_mode
    "profiles": [
        "./profiles/routing-bot-a.json", // E3-3: bot A (conversation+code models A); was ["./profiles/stock-bot.json"]
        "./profiles/routing-bot-b.json", // E3-3: bot B (distinct conversation+code models B)

        // using more than 1 profile requires you to /msg each bot indivually
        // individual profiles override values from the base profile
    ],

    "load_memory": false, // load memory from previous session
    "init_message": "Respond with hello world and your name", // sends to all on spawn
    "only_chat_with": [], // users that the bots listen to and send general messages to. if empty it will chat publicly

    "speak": false,
    // allows all bots to speak through text-to-speech.
    // specify speech model inside each profile with format: {provider}/{model}/{voice}.
    // if set to "system" it will use basic system text-to-speech.
    // Works on windows and mac, but linux requires you to install the espeak package through your package manager eg: `apt install espeak` `pacman -S espeak`.

    "chat_ingame": true, // bot responses are shown in minecraft chat
    "language": "en", // translate to/from this language. Supports these language names: https://cloud.google.com/translate/docs/languages
    "render_bot_view": false, // show bot's view in browser at localhost:3000, 3001...

    "allow_insecure_coding": false, // E1-R2 posture: never auto-run model-written code on the host (kept upstream-false on purpose)
    "allow_vision": false, // allows vision model to interpret screenshots as inputs
    "blocked_actions" : ["!checkBlueprint", "!checkBlueprintLevel", "!getBlueprint", "!getBlueprintLevel"] , // commands to disable and remove from docs. Ex: ["!setMode"]
    "code_timeout_mins": -1, // minutes code is allowed to run. -1 for no timeout
    "relevant_docs_count": 5, // number of relevant code function docs to select for prompting. -1 for all

    "max_messages": 15, // max number of messages to keep in context
    "num_examples": 2, // number of examples to give to the model
    "max_commands": -1, // max number of commands that can be used in consecutive responses. -1 for no limit
    "show_command_syntax": "full", // "full", "shortened", or "none"
    "narrate_behavior": true, // chat simple automatic actions ('Picking up item!')
    "chat_bot_messages": true, // publicly chat messages to other bots

    "spawn_timeout": 30, // num seconds allowed for the bot to spawn before throwing error. Increase when spawning takes a while.
    "block_place_delay": 0, // delay between placing blocks (ms) if using newAction. helps avoid bot being kicked by anti-cheat mechanisms on servers.

    "log_all_prompts": true, // E3-3: log ALL prompts per bot (./bots/<name>/logs) — this is the chat-vs-code routing evidence, was false
};

export default settings;
