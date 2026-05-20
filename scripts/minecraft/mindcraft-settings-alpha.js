// ----------------------------------------------------------------------------
// Committed Mindcraft settings template - points Alpha at the E2 server.
//
// This is the E7-1 non-verbal variant of scripts/minecraft/mindcraft-settings.js.
// `./mindcraft` is git-ignored, so scripts/minecraft/connect-alpha-bot.sh stages
// this reviewed template into the pinned clone as `./mindcraft/settings.js`.
//
// It preserves the E2 connection contract from E3-2:
//   - Minecraft 1.21.6, host 127.0.0.1, port 25565, auth "offline"
//   - headless launch (`auto_open_ui: false`)
//
// E7-1 changes only the Alpha-specific profile and chat surfaces:
//   - one profile: `./profiles/alpha-bot.json`
//   - no spawn init message
//   - no in-game chat, narration, bot-to-bot chat, or voice/TTS
//
// Alpha's identity still comes from agents/alpha/config.yaml and
// agents/alpha/system_prompt.md; this file only suppresses Mindcraft chat
// emission so Alpha remains action-only in the Minecraft world.
// ----------------------------------------------------------------------------
const settings = {
    "minecraft_version": "1.21.6", // E3-2: pinned to the E2 Paper version (E1-R1 / decisions 0001), was "auto"
    "host": "127.0.0.1", // E1-R2: localhost only - offline-mode bots must not be public (decisions 0002)
    "port": 25565, // E3-2: E2 server default, was 55916
    "auth": "offline", // E1-R2: matches Paper online-mode=false (decisions 0002)

    // the mindserver manages all agents and hosts the UI
    "mindserver_port": 8080,
    "auto_open_ui": false, // E3-2: headless connect - no browser UI, was true

    "base_profile": "assistant", // survival, assistant, creative, or god_mode
    "profiles": [ // E7-1: one Alpha bot for the vertical slice; not a generic stock bot
        "./profiles/alpha-bot.json",

        // using more than 1 profile requires you to /msg each bot indivually
        // individual profiles override values from the base profile
    ],

    "load_memory": false, // load memory from previous session
    "init_message": "", // E7-1: no spawn prompt; Alpha must not initiate chat
    "only_chat_with": [], // E7-1: no chat allow-list; chat emission is disabled below

    "speak": false, // E7-1: Alpha has no voice; Python/TTS must not be invoked by Mindcraft
    // allows all bots to speak through text-to-speech.
    // specify speech model inside each profile with format: {provider}/{model}/{voice}.
    // if set to "system" it will use basic system text-to-speech.
    // Works on windows and mac, but linux requires you to install the espeak package through your package manager eg: `apt install espeak` `pacman -S espeak`.

    "chat_ingame": false, // E7-1: suppress bot LLM responses in Minecraft chat
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
    "narrate_behavior": false, // E7-1: suppress automatic action narration such as "Picking up item!"
    "chat_bot_messages": false, // E7-1: Alpha is action-only and must not send public bot messages

    "spawn_timeout": 30, // num seconds allowed for the bot to spawn before throwing error. Increase when spawning takes a while.
    "block_place_delay": 0, // delay between placing blocks (ms) if using newAction. helps avoid bot being kicked by anti-cheat mechanisms on servers.

    "log_all_prompts": false, // log ALL prompts to file
};

export default settings;
