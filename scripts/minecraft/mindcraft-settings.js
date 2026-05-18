// ─────────────────────────────────────────────────────────────────────────────
// Committed Mindcraft settings template — points one stock bot at the E2 server.
//
// This is the reviewed `settings.js` referenced by docs/minecraft/mindcraft-connect.md
// (issue #534, epic E3-2). `./mindcraft` is git-ignored, so the ONLY committed
// artifact is this template; scripts/minecraft/connect-stock-bot.sh stages it
// into the clone as `./mindcraft/settings.js` before launch (same pattern as the
// vendored lockfile in setup-mindcraft.sh / E3-1).
//
// It is a faithful copy of the pinned upstream
//   mindcraft-bots/mindcraft@35be480b4cc0bca990278e6103a1426392559d96/settings.js
// with ONLY the values needed to talk to OUR E2 server changed (every change is
// flagged "E3-2:" inline). Keeping every upstream key means Mindcraft never
// reads an undefined setting.
//
// What changed vs. upstream, and why:
//   - minecraft_version "auto" -> "1.21.6"  (E1-R1 / docs/decisions/0001 — pin to
//     the Paper version scripts/minecraft/start-server.sh provisions; "auto"
//     can mis-detect against a modded/anti-cheat handshake)
//   - port 55916 -> 25565                   (E2 / start-server.sh leaves
//     server.properties server-port unset, so the server listens on Minecraft's
//     default 25565)
//   - host stays "127.0.0.1"                (E1-R2 / docs/decisions/0002 —
//     offline-mode bots only on localhost / a private network)
//   - auth stays "offline"                  (E1-R2 / docs/decisions/0002)
//   - auto_open_ui true -> false            (headless connect; no browser UI)
//   - profiles -> ["./profiles/stock-bot.json"]  (one stock bot; our 9 agents
//     are E8, not this issue)
//
// host/port/profile are env-overridable by the launch script (MC_HOST / MC_PORT
// / MINDCRAFT_PROFILE) — see connect-stock-bot.sh --help.
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
        "./profiles/stock-bot.json", // E3-2: one stock bot; our 9 agents are E8

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

    "log_all_prompts": false, // log ALL prompts to file
};

export default settings;
