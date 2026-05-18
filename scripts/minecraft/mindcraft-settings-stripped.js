// ─────────────────────────────────────────────────────────────────────────────
// Committed Mindcraft settings template — stock bot with Python-superseded
// Mindcraft features disabled (E3-5).
//
// This is the reviewed `settings.js` referenced by
// docs/minecraft/mindcraft-stripped-features.md (issue #537, epic E3-5). It
// reduces Mindcraft's surface area and cost by turning OFF the features the
// Python "brain" already owns (example/skill-doc retrieval, auto-narration,
// session memory, voice, vision), while still connecting and acting against the
// E2 server. `./mindcraft` is git-ignored, so the ONLY committed artifact is
// this template; scripts/minecraft/connect-stripped-bot.sh stages it into the
// clone as `./mindcraft/settings.js` before launch (same committed-artifact
// pattern as connect-stock-bot.sh / E3-2 and mindcraft-settings-routing.js /
// E3-3).
//
// It is a faithful copy of scripts/minecraft/mindcraft-settings.js (the reviewed
// E3-2 stock-bot template, itself a faithful copy of pinned upstream
//   mindcraft-bots/mindcraft@35be480b4cc0bca990278e6103a1426392559d96/settings.js)
// with ONLY the redundancy-disabling keys changed (every change is flagged
// "E3-5:" inline with its rationale and the decision it binds to). Keeping every
// other key verbatim means Mindcraft never reads an undefined setting and the
// E3-2 E2-server connect contract is preserved unchanged.
//
// The Mindcraft settings.js keys ARE the reversible config flags: flipping a
// value back re-enables the feature with no fork-core edit, satisfying this
// issue's scope ("Out: irreversible deletion of fork core").
//
// What changed vs. the E3-2 stock-bot template, and why (full table +
// reversibility in docs/minecraft/mindcraft-stripped-features.md):
//   - num_examples        2  -> 0      (Mindcraft in-context example retrieval
//                                        superseded by the Python 3-tier memory
//                                        service — decision 0003 says
//                                        disable/de-emphasize Mindcraft examples
//                                        until E5; OpenRouter class has no
//                                        embeddings)
//   - relevant_docs_count 5  -> 0      (Mindcraft skill-doc retrieval superseded
//                                        by the same Python memory service —
//                                        decision 0003; no embedding provider)
//   - narrate_behavior    true -> false (Python owns what is surfaced/streamed;
//                                        cuts redundant auto-chat — decision 0004
//                                        keeps Python the source of truth for
//                                        surfaced output)
//
// Comment-only (already upstream-false; E3-5 records WHY we keep them off and the
// Python system that supersedes each — no value change, so still trivially
// reversible):
//   - load_memory   off — Mindcraft session memory   -> Python pgvector memory (E5 / 0003)
//   - speak         off — Mindcraft voice/TTS         -> Python Edge TTS        (0003)
//   - allow_vision  off — Mindcraft vision tier unused; cost/surface reduction  (0003)
//
// Deliberately KEPT ON: bot-to-bot conversation (`chat_bot_messages` and the
// Mindcraft conversation system) — decision 0004 keeps Mindcraft's decentralized
// pairwise conversation as the base; it is NOT stripped here.
//
// host/port/profiles are env-overridable by the launch script (MC_HOST / MC_PORT
// / MINDCRAFT_PROFILE) — see connect-stripped-bot.sh --help.
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

    "load_memory": false, // E3-5: KEEP off — Mindcraft session memory superseded by the Python 3-tier (pgvector) memory service (E5 / decision 0003); reverse: set true
    "init_message": "Respond with hello world and your name", // sends to all on spawn
    "only_chat_with": [], // users that the bots listen to and send general messages to. if empty it will chat publicly

    "speak": false, // E3-5: KEEP off — voice/TTS is owned by the Python Edge TTS pipeline, not Mindcraft (decision 0003 keeps voice Python-side); reverse: set true (then see the upstream TTS notes below)
    // allows all bots to speak through text-to-speech.
    // specify speech model inside each profile with format: {provider}/{model}/{voice}.
    // if set to "system" it will use basic system text-to-speech.
    // Works on windows and mac, but linux requires you to install the espeak package through your package manager eg: `apt install espeak` `pacman -S espeak`.

    "chat_ingame": true, // bot responses are shown in minecraft chat
    "language": "en", // translate to/from this language. Supports these language names: https://cloud.google.com/translate/docs/languages
    "render_bot_view": false, // show bot's view in browser at localhost:3000, 3001...

    "allow_insecure_coding": false, // E1-R2 posture: never auto-run model-written code on the host (kept upstream-false on purpose)
    "allow_vision": false, // E3-5: KEEP off — Mindcraft vision tier unused; cost/surface reduction (decision 0003 — no Mindcraft vision tier); reverse: set true
    "blocked_actions" : ["!checkBlueprint", "!checkBlueprintLevel", "!getBlueprint", "!getBlueprintLevel"] , // commands to disable and remove from docs. Ex: ["!setMode"]
    "code_timeout_mins": -1, // minutes code is allowed to run. -1 for no timeout
    "relevant_docs_count": 0, // E3-5: 5->0 — Mindcraft skill-doc retrieval superseded by the Python 3-tier memory service; OpenRouter class has no embeddings (decision 0003); reverse: restore 5

    "max_messages": 15, // max number of messages to keep in context
    "num_examples": 0, // E3-5: 2->0 — Mindcraft in-context example retrieval superseded by the Python 3-tier memory service (decision 0003 — disable/de-emphasize Mindcraft examples until E5); reverse: restore 2
    "max_commands": -1, // max number of commands that can be used in consecutive responses. -1 for no limit
    "show_command_syntax": "full", // "full", "shortened", or "none"
    "narrate_behavior": false, // E3-5: true->false — Python owns what is surfaced/streamed; cuts redundant auto-chat (decision 0004 — Python is the source of truth for surfaced output); reverse: restore true
    "chat_bot_messages": true, // E3-5: KEEP true — decentralized bot-to-bot conversation is the base (decision 0004); deliberately NOT stripped

    "spawn_timeout": 30, // num seconds allowed for the bot to spawn before throwing error. Increase when spawning takes a while.
    "block_place_delay": 0, // delay between placing blocks (ms) if using newAction. helps avoid bot being kicked by anti-cheat mechanisms on servers.

    "log_all_prompts": false, // log ALL prompts to file
};

export default settings;
