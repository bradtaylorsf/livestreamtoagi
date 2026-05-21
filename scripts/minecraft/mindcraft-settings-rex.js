// ----------------------------------------------------------------------------
// Committed Mindcraft settings template - points Rex at the E2 server.
//
// This is the E8-2 verbal cohort variant of mindcraft-settings-alpha.js.
// scripts/minecraft/connect-rex-bot.sh stages this reviewed template into
// the pinned, git-ignored ./mindcraft clone as settings.js.
//
// Contract:
//   - Minecraft 1.21.6, host 127.0.0.1, port 25565, auth "offline"
//   - headless launch (auto_open_ui: false)
//   - one profile: ./profiles/rex-bot.json
//   - no spawn init message; decentralized respond/ignore is E8-5/E8-6
//   - Rex is verbal in Minecraft chat; TTS remains Python-side
// ----------------------------------------------------------------------------
const settings = {
    "minecraft_version": "1.21.6",
    "host": "127.0.0.1",
    "port": 25565,
    "auth": "offline",

    "mindserver_port": 8080,
    "auto_open_ui": false,

    "base_profile": "assistant",
    "profiles": [
        "./profiles/rex-bot.json",
    ],

    "load_memory": false,
    "init_message": "",
    "only_chat_with": [],

    "speak": false,

    "chat_ingame": true,
    "language": "en",
    "render_bot_view": false,

    "allow_insecure_coding": false,
    "allow_vision": false,
    "blocked_actions" : ["!checkBlueprint", "!checkBlueprintLevel", "!getBlueprint", "!getBlueprintLevel"],
    "code_timeout_mins": -1,
    "relevant_docs_count": 5,

    "max_messages": 15,
    "num_examples": 2,
    "max_commands": -1,
    "show_command_syntax": "full",
    "narrate_behavior": true,
    "chat_bot_messages": true,

    "spawn_timeout": 30,
    "block_place_delay": 0,

    "log_all_prompts": false,
};

export default settings;
