<!-- managed by alpha-loop -->
Updated AGENTS.md with these changes:

**Numbers corrected:**
- Tool modules: 13 → 15 (added character_tools, economy_tools, social_tools)
- Tool class exports: 20 → 30 (new alliance, economy, character, and audience tools)
- Migrations: 21 pairs (up to 021) → 30 pairs (up to `030_goal_source_dream`)
- Repo classes: 15 → 17 (added agent_state_repo, alliance_repo)
- Event types: 18 → 19 (added CONVERSATION_PRODUCTIVITY)
- Model classes: ~102 → 106
- Test files: ~76 → ~89

**New subsystems added:**
- `core/characters/` — spawner, voting, departure for dynamic agent creation
- `core/events/` — event_generator, event_templates for world events
- `core/social/alliances.py` — alliance formation/dissolution (was just relationship_tracker)
- `core/agent_economy` referenced in tool dependencies

**Config directory updated:**
- Added event_config.yaml and recurring_personas.yaml (4 → 6 files)

**Scripts updated:**
- Added run_reflection_test.py to the listing

**Important files expanded:**
- Added `core/characters/spawner.py`, `core/characters/voting.py`, `core/social/alliances.py`

**Stale info removed:**
- Old tool category descriptions replaced with current set including alliances, economy, character proposals
