<!-- managed by alpha-loop -->
Updated AGENTS.md with the following key changes:

**Added:**
- Conversation engine orchestrator and its subsystems (`core/conversation/`)
- TTS pipeline with per-agent voices and speech parser
- Overseer content review system
- Tool registry with 18 implemented tools (was "placeholder")
- Memory managers and reflection system details
- `scripts/` now lists chat.py, test_agent.py, watch_conversations.py
- ~42 backend test files (was ~20)
- Guidelines for new tool creation (extend `BaseTool`, register in `__init__.py`)
- Memory subsystem boundary rule (use managers, not direct repo calls)
- Docker sandbox service for code execution

**Updated:**
- Migrations: 6 files up to `006_self_modification_fields` (was 4)
- `tools/` is fully implemented, not a placeholder
- Directory structure reflects `core/conversation/` subpackage
- Important files now includes conversation_engine.py, reflection.py, tools/__init__.py
- Website port clarified as `4000` in root dev script
- Non-negotiables reflect that conversation engine exists but no production entry point yet

**Preserved:** All project-specific rules, special agent handling, port alignment requirements, 5-section structure, managed-by marker.
