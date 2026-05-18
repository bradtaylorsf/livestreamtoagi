"""Fork-source routing contract (issue #539, epic E3-7).

**Conditional premise reconciliation.** E1-R3 / decision 0003 *"Patch Scope"*
concluded **no fork patch is required** for per-agent/per-tier routing, and
E3-3 ([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535))
verified native routing with no patch. So E3-7's literal trigger ("a patch is
required and E3-3 was non-trivial") is **not met** — there is no routing patch
to harden.

The acceptance criterion still binds: *"Tests fail if per-agent/per-tier
routing breaks."* Every existing E3-3 test
(``tests/backend/test_mc_model_routing.py``) only inspects **repo-side**
committed assets (profile/settings templates, the launch script, docs,
``core/llm_client.py``). **None inspects the pinned Mindcraft fork source.** So
the E3-6 ([#538](https://github.com/bradtaylorsf/livestreamtoagi/issues/538))
upstream-rebase flow could silently change Mindcraft's ``Prompter`` to ignore
``code_model`` or collapse the chat/code tiers and **all those tests stay
green** — exactly the "an upstream rebase can't silently break the thesis"
risk E3-7 names. This module closes that gap by asserting the routing contract
**against the fork source itself**.

Offline posture mirrors the E3-3/E3-5 siblings: the fork-source checks
``skipif`` when the disposable ``./mindcraft`` clone is absent (CI has no clone
— the suite stays green), and assert only when it is present. The
config/doc/wiring checks are dependency-free and always run.

Maps to E3-7's three named concerns:

* **(a) model selection** — ``src/models/prompter.js`` still constructs
  *separate* chat (``profile.model`` → conversation tier) and code
  (``profile.code_model`` → building tier) models, and ``src/models/_model_map.js``
  still dispatches the ``lmstudio/`` / ``openrouter/`` string prefixes to
  *distinct* provider classes (decision 0003 *Evidence*: prompter.js
  chat/code construction + code_model coding path; _model_map.js dynamic
  API selection).
* **(b) fallback** — ``src/models/openrouter.js`` / ``src/models/lmstudio.js``
  exist and expose the provider/``sendRequest`` surface, the documented
  string-syntax provider path, and the OpenRouter-has-no-embeddings caveat
  (0003) the word-overlap example fallback depends on.
* **(c) cost attribution** — the zero-external-spend boundary as a *negative*
  contract (committed runtime profiles never carry ``openrouter/``; the
  Mindcraft providers never write our DB → cost stays Python-side per 0003),
  plus the per-agent ``chat != code`` thesis re-asserted through the same
  ``core.llm_client`` alias/registry path E3-3 uses, derived from
  ``agents/<id>/config.yaml`` (no hard-coded model strings → cannot drift).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]

# Pinned fork commit (E1-R1 → decision 0001/0003). Recorded here only so the
# informational SHA test can flag when the inspected clone has been re-based.
PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"

# The disposable clone — same default + env override as the connect scripts
# (`MINDCRAFT_DIR`, default `./mindcraft`). Resolved against the repo root so
# the test does not depend on the caller's cwd.
_env_dir = os.environ.get("MINDCRAFT_DIR")
MINDCRAFT_DIR = Path(_env_dir) if _env_dir else REPO_ROOT / "mindcraft"
MODELS_DIR = MINDCRAFT_DIR / "src" / "models"
PROMPTER_JS = MODELS_DIR / "prompter.js"
MODEL_MAP_JS = MODELS_DIR / "_model_map.js"
OPENROUTER_JS = MODELS_DIR / "openrouter.js"
LMSTUDIO_JS = MODELS_DIR / "lmstudio.js"

# Repo-side artifacts the dependency-free checks assert on.
PROFILES_DIR = REPO_ROOT / "scripts" / "minecraft" / "profiles"
ROUTING_DOC = REPO_ROOT / "docs" / "minecraft" / "model-routing.md"
FORK_MAINT_DOC = REPO_ROOT / "docs" / "minecraft" / "fork-maintenance.md"
DECISION_0003 = REPO_ROOT / "docs" / "decisions" / "0003-mindcraft-model-routing.md"
PACKAGE_JSON = REPO_ROOT / "package.json"
VERA_CONFIG = REPO_ROOT / "agents" / "vera" / "config.yaml"
AURORA_CONFIG = REPO_ROOT / "agents" / "aurora" / "config.yaml"


def _clone_head() -> str | None:
    """HEAD sha of the disposable clone, or ``None`` when it is absent."""
    if not (MINDCRAFT_DIR / ".git").is_dir():
        return None
    proc = subprocess.run(
        ["git", "-C", str(MINDCRAFT_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


CLONE_HEAD = _clone_head()

# Skip the fork-source contract (only) when there is no clone to inspect — the
# config/doc/wiring guards below still run and keep CI green. When the clone IS
# present (a developer machine, or an E3-6 re-base validation host) the
# contract is enforced regardless of which commit it sits at: catching a
# re-based clone that silently broke routing is the entire point of E3-7.
needs_clone = pytest.mark.skipif(
    CLONE_HEAD is None,
    reason=(
        f"no Mindcraft clone at {MINDCRAFT_DIR} — fork-source routing contract "
        "is skipped (CI has no clone; run scripts/minecraft/setup-mindcraft.sh "
        "to enforce it locally / on an E3-6 re-base host)"
    ),
)

# Every fork-source assertion failure points the reader at the two documents
# E3-7 says to re-review: the E3-6 re-base runbook and decision 0003 Evidence.
REBASE_HINT = (
    "↳ The pinned Mindcraft fork's native routing contract changed — an "
    "upstream re-base most likely did this. Before accepting a new pin, "
    "re-review docs/minecraft/fork-maintenance.md (\"How to re-base on "
    "upstream\") and the 'Evidence' lines in "
    "docs/decisions/0003-mindcraft-model-routing.md, then update "
    "docs/minecraft/model-routing.md if the native behavior genuinely moved."
)


def _src(path: Path) -> str:
    assert path.is_file(), (
        f"missing fork source {path} (clone HEAD={CLONE_HEAD}). {REBASE_HINT}"
    )
    return path.read_text(encoding="utf-8")


def _assert_re(pattern: str, text: str, where: str, why: str) -> None:
    assert re.search(pattern, text), (
        f"{where}: expected /{pattern}/ — {why}\n{REBASE_HINT}"
    )


def _resolve_canonical(openrouter_id: str) -> str:
    """Resolve a bare ``provider/model`` id through the llm_client maps.

    Same path E3-3's ``test_mc_model_routing.py`` uses — reused (not
    re-hard-coded) so the per-agent thesis cannot drift from
    ``core/llm_client.py``.
    """
    canonical = MODEL_NAME_ALIASES.get(openrouter_id, openrouter_id)
    assert canonical in MODEL_REGISTRY, (
        f"{openrouter_id!r} does not resolve into MODEL_REGISTRY via "
        f"MODEL_NAME_ALIASES (got {canonical!r})"
    )
    return canonical


# ── (a) model selection: prompter.js builds SEPARATE chat & code models ──────

# The per-tier wiring contract, one row per routing tier. Parametrized so a
# re-base that breaks exactly one tier fails that row loudly while the other
# passes — pinpointing which tier upstream collapsed.
TIER_CONTRACT = {
    "conversation": {
        "profile_field": "model",
        # profile.model → selectAPI → createModel → this.chat_model
        "select": r"selectAPI\(\s*this\.profile\.model\s*\)",
        "construct": r"this\.chat_model\s*=\s*createModel\(",
        # conversation generation dispatches through chat_model
        "dispatch": r"this\.chat_model\.sendRequest\(",
    },
    "building": {
        "profile_field": "code_model",
        # guarded by `if (this.profile.code_model)`, its OWN selectAPI+createModel
        "guard": r"if\s*\(\s*this\.profile\.code_model\s*\)",
        "select": r"selectAPI\(\s*this\.profile\.code_model\s*\)",
        "construct": r"this\.code_model\s*=\s*createModel\(",
        # promptCoding (the building/code tier) dispatches through code_model
        "dispatch": r"this\.code_model\.sendRequest\(",
    },
}


@needs_clone
@pytest.mark.parametrize("tier", sorted(TIER_CONTRACT))
def test_prompter_wires_each_routing_tier_independently(tier):
    """Each tier: ``profile.<field>`` → ``selectAPI`` → ``createModel`` → its
    own model attr, dispatched on the matching prompt path. A single broken
    tier fails only its own row."""
    src = _src(PROMPTER_JS)
    spec = TIER_CONTRACT[tier]
    field = spec["profile_field"]
    if "guard" in spec:
        _assert_re(
            spec["guard"], src, "prompter.js",
            f"the {tier} tier must stay guarded by `if (this.profile.{field})` "
            "(decision 0003 Evidence: prompter.js chat/code construction)",
        )
    _assert_re(
        spec["select"], src, "prompter.js",
        f"the {tier} tier must still select its API from profile.{field}",
    )
    _assert_re(
        spec["construct"], src, "prompter.js",
        f"the {tier} tier must construct its own model via createModel()",
    )
    _assert_re(
        spec["dispatch"], src, "prompter.js",
        f"the {tier} tier must dispatch through its own model "
        "(decision 0003 Evidence: prompter.js code_model coding path)",
    )


@needs_clone
def test_prompter_keeps_chat_and_code_models_separate_with_documented_fallback():
    """Two *independent* createModel() calls (chat & code), plus the
    documented ``code_model = chat_model`` fallback for profiles with no
    ``code_model``. If a re-base collapsed the tiers to a single model the
    second createModel() vanishes and this fails loudly."""
    src = _src(PROMPTER_JS)
    chat_construct = TIER_CONTRACT["conversation"]["construct"]
    code_construct = TIER_CONTRACT["building"]["construct"]
    assert re.search(chat_construct, src) and re.search(code_construct, src), (
        "prompter.js must construct chat_model AND code_model separately — "
        "collapsing them makes per-tier routing vacuous.\n" + REBASE_HINT
    )
    # The documented fallback: a profile with no code_model reuses chat_model.
    _assert_re(
        r"this\.code_model\s*=\s*this\.chat_model", src, "prompter.js",
        "the no-code_model fallback (code_model := chat_model) must remain — "
        "single-model profiles still need a working code tier",
    )


@needs_clone
def test_model_map_dispatches_string_prefixes_to_distinct_provider_classes():
    """``_model_map.js`` keys providers by each class's static ``prefix`` and
    selects by ``profile.model.startsWith(<prefix>)``. With openrouter.js and
    lmstudio.js declaring distinct prefixes (asserted below) this proves the
    ``openrouter/`` and ``lmstudio/`` strings dispatch to *distinct* classes
    (decision 0003 Evidence: Mindcraft dynamic API selection)."""
    src = _src(MODEL_MAP_JS)
    _assert_re(
        r"hasOwnProperty\.call\(\s*exported\s*,\s*['\"]prefix['\"]\s*\)",
        src, "_model_map.js",
        "providers must still be discovered by their static `prefix`",
    )
    _assert_re(
        r"map\[\s*prefix\s*\]\s*=\s*exported", src, "_model_map.js",
        "the prefix → class map must still be built",
    )
    _assert_re(
        r"profile\.model\?\.startsWith\(\s*key\s*\)", src, "_model_map.js",
        "the model string prefix must still select the provider api",
    )
    _assert_re(
        r"profile\.model\.replace\(\s*profile\.api\s*\+\s*['\"]/['\"]",
        src, "_model_map.js",
        "the `<provider>/` prefix must still be stripped before the call",
    )
    _assert_re(
        r"new\s+apiMap\[\s*profile\.api\s*\]\(", src, "_model_map.js",
        "the resolved api must still instantiate its own provider class",
    )


# ── (b) fallback: provider classes + documented surface intact ──────────────

PROVIDER_CONTRACT = {
    "openrouter": {
        "path": OPENROUTER_JS,
        "class": "OpenRouter",
        "prefix": "openrouter",
        # OpenRouter has NO embeddings (decision 0003 caveat): the word-overlap
        # example-selection fallback depends on this staying true.
        "extra": (
            r"Embeddings are not supported",
            "openrouter.js must keep throwing on embed() — the 0003 "
            "word-overlap example fallback depends on this",
        ),
    },
    "lmstudio": {
        "path": LMSTUDIO_JS,
        "class": "LMStudio",
        "prefix": "lmstudio",
        # LM Studio embeddings are the 0003-preferred local path.
        "extra": (
            r"async\s+embed\s*\(",
            "lmstudio.js must keep its embed() surface — the 0003-preferred "
            "local embedding path",
        ),
    },
}


@needs_clone
@pytest.mark.parametrize("provider", sorted(PROVIDER_CONTRACT))
def test_provider_class_exposes_documented_routing_surface(provider):
    spec = PROVIDER_CONTRACT[provider]
    src = _src(spec["path"])
    _assert_re(
        rf"export\s+class\s+{spec['class']}\b", src, spec["path"].name,
        f"the {spec['class']} provider class must still be exported",
    )
    _assert_re(
        rf"static\s+prefix\s*=\s*['\"]{spec['prefix']}['\"]",
        src, spec["path"].name,
        f"the {provider} string prefix must stay '{spec['prefix']}' — "
        "_model_map.js keys the dispatch map by it",
    )
    _assert_re(
        r"async\s+sendRequest\s*\(", src, spec["path"].name,
        f"{provider} must keep the sendRequest() surface prompter.js calls",
    )
    extra_pat, extra_why = spec["extra"]
    _assert_re(extra_pat, src, spec["path"].name, extra_why)


@needs_clone
def test_lmstudio_and_openrouter_are_distinct_provider_classes():
    """The two providers must declare different class names AND different
    string prefixes — otherwise the chat/code tiers could silently collapse
    onto one provider after a re-base."""
    or_src = _src(OPENROUTER_JS)
    lm_src = _src(LMSTUDIO_JS)
    or_prefix = re.search(r"static\s+prefix\s*=\s*['\"]([^'\"]+)['\"]", or_src)
    lm_prefix = re.search(r"static\s+prefix\s*=\s*['\"]([^'\"]+)['\"]", lm_src)
    assert or_prefix and lm_prefix, (
        "both provider classes must declare a static prefix.\n" + REBASE_HINT
    )
    assert or_prefix.group(1) != lm_prefix.group(1), (
        f"openrouter and lmstudio share prefix {or_prefix.group(1)!r} — "
        "the two routing providers would collapse onto one.\n" + REBASE_HINT
    )
    assert "class OpenRouter" in or_src and "class LMStudio" in lm_src, (
        "the two provider class names must remain distinct.\n" + REBASE_HINT
    )


# ── (c) cost attribution: zero-external-spend negative contract ─────────────


def test_committed_runtime_profiles_never_carry_openrouter():
    """Negative contract: the profiles actually launched
    (``scripts/minecraft/profiles/*.json``) stay ``lmstudio/``-only so a local
    routing run incurs **zero external model spend** (decision 0003 — cost
    controls are Python-side E4/E11, not Mindcraft). This is dependency-free
    and always runs."""
    profiles = sorted(PROFILES_DIR.glob("*.json"))
    assert profiles, f"no committed runtime profiles under {PROFILES_DIR}"
    for path in profiles:
        raw = path.read_text(encoding="utf-8")
        assert "openrouter/" not in raw, (
            f"{path.name} carries an 'openrouter/' id — committed runtime "
            "profiles must stay local-only (decision 0003 zero-spend "
            "boundary). The production openrouter/ reference lives in "
            "docs/minecraft/model-routing.md, never in a launched profile."
        )


@needs_clone
def test_mindcraft_providers_do_not_write_our_cost_or_db_stack():
    """Negative contract: the Mindcraft provider source contains no reference
    to our cost/observability/DB stack — proving cost attribution stays
    Python-side per decision 0003 (Mindcraft never tracks cost in our DB)."""
    forbidden = ("langfuse", "psycopg", "DATABASE_URL", "cost_governor", "asyncpg")
    for path in (OPENROUTER_JS, LMSTUDIO_JS):
        src = _src(path).lower()
        for token in forbidden:
            assert token.lower() not in src, (
                f"{path.name} references {token!r} — Mindcraft providers must "
                "NOT write our DB/cost stack; cost stays Python-side "
                "(decision 0003).\n" + REBASE_HINT
            )


@pytest.mark.parametrize(
    ("config_path", "agent"),
    [(VERA_CONFIG, "vera"), (AURORA_CONFIG, "aurora")],
)
def test_per_agent_chat_differs_from_code_through_llm_client(config_path, agent):
    """The thesis: each agent routes a conversation model distinct from its
    building model. Derived from ``agents/<id>/config.yaml`` (single source of
    truth) and resolved through the SAME ``core.llm_client`` alias/registry
    path E3-3 uses — no hard-coded model strings, so it cannot drift. This is
    dependency-free and always runs (the per-tier thesis must hold even on a
    host with no clone)."""
    cfg = yaml.safe_load(config_path.read_text())
    conv_canonical = _resolve_canonical(cfg["model_conversation"])
    build_canonical = _resolve_canonical(cfg["model_building"])
    assert conv_canonical != build_canonical, (
        f"{agent}: conversation ({conv_canonical}) and building "
        f"({build_canonical}) resolve to the same model — per-tier routing "
        "would be vacuous. Fix agents/" + agent + "/config.yaml or "
        "core/llm_client.py."
    )


# ── Informational + wiring/doc guards (dependency-free, always run) ──────────


@needs_clone
def test_inspected_clone_sha_is_recorded_for_rebase_visibility():
    """Not a hard pin (E3-7's job is to *survive* re-pins): just surface which
    commit the contract was enforced against, so a re-based clone is visible
    in the test log instead of silent."""
    assert CLONE_HEAD, "clone HEAD should be resolvable when the .git dir exists"
    if CLONE_HEAD != PINNED_SHA:
        # A re-based clone is exactly the E3-6 scenario this module guards;
        # the contract assertions above still ran against it.
        print(
            f"\n[E3-7] fork-source routing contract enforced against "
            f"{CLONE_HEAD} (documented pin is {PINNED_SHA}). If this was an "
            "E3-6 re-base, confirm docs/minecraft/fork-maintenance.md step 6 "
            "updated every pin record."
        )


def test_package_json_wires_verify_mindcraft_routing_contract():
    """The CI ``backend-test`` job auto-picks ``tests/backend/`` — this script
    follows the existing ``verify:mindcraft-*`` convention (no new CI infra,
    same as E3-6)."""
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    cmd = scripts.get("verify:mindcraft-routing-contract")
    assert cmd, "package.json missing verify:mindcraft-routing-contract"
    assert "test_mc_routing_fork_contract.py" in cmd, (
        "verify:mindcraft-routing-contract must run this contract module"
    )


def test_model_routing_doc_records_e3_7_premise_not_met():
    """The runbook must record that E3-7's conditional premise was not met
    (native routing, no patch to harden) and link this guard + the E3-6
    re-base runbook."""
    text = ROUTING_DOC.read_text()
    assert "#539" in text and "E3-7" in text
    assert "test_mc_routing_fork_contract.py" in text, (
        "model-routing.md must link the new fork-source contract test"
    )
    assert "fork-maintenance.md" in text, (
        "model-routing.md must link the E3-6 re-base runbook E3-7 protects"
    )


def test_decision_0003_back_references_e3_7():
    """Decision 0003 'Patch Scope' must back-reference E3-7/#539 the same way
    it already back-references E3-3/#535 and E3-5/#537."""
    text = DECISION_0003.read_text()
    assert "#539" in text and "E3-7" in text, (
        "decision 0003 must record E3-7/#539 resolved as 'no patch required; "
        "native-routing contract now guarded against upstream re-base'"
    )
    assert "test_mc_routing_fork_contract.py" in text


def test_fork_maintenance_doc_wires_the_routing_contract_into_the_rebase_flow():
    """Every fork-source failure tells the reader to re-review the E3-6 re-base
    runbook — that doc must exist *and* actually instruct running this contract
    at the moment a re-based clone is present.

    This is the linchpin of E3-7: the fork-source assertions ``skipif`` when no
    clone exists (CI), so the *only* moment they execute is during an E3-6
    re-base. If the runbook never tells the re-baser to run
    ``verify:mindcraft-routing-contract``, a routing-breaking upstream re-base
    ships silently — exactly the regression vector E3-7 names — even though
    this module is correct. Asserting the wiring here makes it un-silenceable
    (symmetric with ``test_model_routing_doc_records_e3_7_premise_not_met``)."""
    assert FORK_MAINT_DOC.is_file(), (
        f"missing {FORK_MAINT_DOC} — the REBASE_HINT points here"
    )
    text = FORK_MAINT_DOC.read_text()
    assert "verify:mindcraft-routing-contract" in text, (
        "docs/minecraft/fork-maintenance.md ('How to re-base on upstream') "
        "must instruct running `pnpm verify:mindcraft-routing-contract` "
        "against the freshly re-based clone — that is the only moment this "
        "fork-source contract executes (it skips in CI). Without it an E3-6 "
        "re-base can silently break per-tier routing, defeating E3-7."
    )
