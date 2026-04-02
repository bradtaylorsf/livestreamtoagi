1. Files to create/modify

- `agents/fork/config.yaml`
  - Align Fork's scalar config with the canonical values already used by the loader.
  - Add `closing_weight: 0.05` only if the config schema is updated to support it.
- `agents/fork/system_prompt.md`
  - Keep the prompt faithful to the character sheet, but trim wording if needed so the prompt-length test has a stable margin.
- `agents/fork/behaviors.yaml`
  - Ensure the behavior keys cover code review, open-source alternatives, and license/data-sovereignty checks.
- `core/models.py`
  - Add a typed `closing_weight` field to `AgentConfig` if this issue is expected to make that value available at runtime; otherwise the YAML value will be ignored by Pydantic.
- `tests/backend/test_agent_registry.py`
  - Add Fork-specific assertions for config loading and prompt/behavior contents.
  - Add a prompt-length/token-budget test for Fork.

2. Key implementation details

- Use `deepseek-v3.2`, not `deepseek/deepseek-v3.2`, in `config.yaml`. The registry validates against `core/llm_client.py`, and the slash-prefixed string will be rejected.
- The `fork/` directory already exists and mostly matches the character sheet. Treat this as a reconcile/update task, not a greenfield create-from-scratch task.
- `closing_weight` is not part of `AgentConfig` today. If acceptance requires it as real config rather than dead YAML, the schema must be updated and tests should assert the value after registry load.
- The current loader reads `system_prompt.md` as plain text and `behaviors.yaml` only when the YAML root is a mapping. Keep `behaviors.yaml` as a top-level object, not a list.
- There is no existing token-limit helper in tests. Pick one deterministic rule for the new test and encode it explicitly:
  - preferred: a tokenizer already available in the lockfile/environment if importable
  - fallback: a conservative character or word ceiling documented in the test

3. Edge cases to handle

- Do not introduce a model name that is missing from `MODEL_REGISTRY`, or Fork will be skipped during `AgentRegistry.load_all()`.
- If `closing_weight` is added to YAML without updating `AgentConfig`, tests can still pass accidentally unless they verify the loaded model object, not just raw file contents.
- Keep catchphrases exact, including punctuation/casing, if tests assert string membership.
- Avoid making the prompt so long that the new token-budget test becomes brittle; leave headroom for future edits.
- Preserve the existing 9-agent load expectation in `tests/backend/test_agent_registry.py`; changes for Fork should not alter the roster or special-agent behavior.
