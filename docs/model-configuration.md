# Model Configuration

Model selection is environment-driven through logical roles. The backend still
keeps legacy defaults for bootstrapping, but runtime callers should use model
roles rather than provider IDs in code or checked-in agent configs.

## Local Provider Split

`LTAG_MODEL_*` chooses the logical model role. When `LLM_PROVIDER=lmstudio` or
another local OpenAI-compatible provider is active, the actual model sent to the
local server still comes from:

- `LOCAL_LLM_MODEL` for conversation/fast roles
- `LOCAL_LLM_MODEL_BUILDING` for building-tier roles
- `LOCAL_LLM_PASSTHROUGH_MODEL=true` only when the request model should be sent
  through exactly as written

That means a local Minecraft run can set all logical roles to cheap known names,
while LM Studio receives the loaded local model ID from `LOCAL_LLM_MODEL`.

## Global Role Overrides

- `LTAG_MODEL_FAST`: default for cheap classifiers, filters, summaries, world
  events, and short internal calls
- `LTAG_MODEL_BUILDING`: default for planning, eval, reflection fallback, and
  other heavier structured calls
- `LTAG_MODEL_CONVERSATION`: default for agent conversation models
- `LTAG_MODEL_AGENT_DEFAULT_CONVERSATION`: default conversation model for agents
- `LTAG_MODEL_AGENT_DEFAULT_BUILDING`: default building model for agents

## Per-Agent Overrides

Use uppercase agent IDs:

```bash
export LTAG_MODEL_AGENT_REX_CONVERSATION=openai/gpt-4o-mini
export LTAG_MODEL_AGENT_REX_BUILDING=deepseek/deepseek-v3.2
```

Checked-in agent configs use `model:agent:<id>:conversation` and
`model:agent:<id>:building`, so these variables override YAML without editing
agent files.

## Internal Role Overrides

- `LTAG_MODEL_MANAGEMENT_FILTER`
- `LTAG_MODEL_TOPIC_CLASSIFIER`
- `LTAG_MODEL_MEMORY_SUMMARY`
- `LTAG_MODEL_CONVERSATION_SUMMARY`
- `LTAG_MODEL_CONVERSATION_COMMITMENTS`
- `LTAG_MODEL_DREAM_FALLBACK`
- `LTAG_MODEL_REFLECTION_FALLBACK`
- `LTAG_MODEL_DEPARTURE_NARRATIVE`
- `LTAG_MODEL_CHARACTER_DEFAULT_CONVERSATION`
- `LTAG_MODEL_CHARACTER_DEFAULT_BUILDING`
- `LTAG_MODEL_CHARACTER_CONCEPT`
- `LTAG_MODEL_CHARACTER_CONFIG`
- `LTAG_MODEL_CHARACTER_SYSTEM_PROMPT`
- `LTAG_MODEL_WORLD_EVENT`
- `LTAG_MODEL_WORLD_REVENUE`
- `LTAG_MODEL_RECURRING_PERSONA_COMMENT`
- `LTAG_MODEL_RECURRING_PERSONA_CHAT`
- `LTAG_MODEL_SIMULATION_LEARNING_SUMMARY`
- `LTAG_MODEL_EVAL_ENGINE`
- `LTAG_MODEL_EVAL_ANALYZER`
- `LTAG_MODEL_RELATIONSHIP_SENTIMENT`
- `LTAG_MODEL_ALPHA_DISPATCH`

Role-specific variables win first, then the global role defaults above, then the
legacy defaults in `core/model_config.py`.
