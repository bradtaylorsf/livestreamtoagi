"""Tests for the bridge transport & protocol decision record (issue #540, E4-1).

E4-1 is **ADR-only** — it adds no code. The acceptance criterion is structural:
``docs/decisions/0010-bridge-protocol.md`` must exist, follow the established
ADR format, and stay *consistent with E1-R5* — i.e. it must not contradict the
bridge contract already fixed by ``0005-skill-extension-point.md`` and recorded
in ``0000-summary.md``. It must also be reachable from the decision index.

These checks are dependency-free (pure file reads — no Node, no Minecraft, no
network, no Docker, no LLM) and assert on **stable committed anchors** (the
endpoint path, the auth env var, the envelope field names, the typed service
names) and on **cross-document agreement** rather than prose, so they enforce
the "consistent with E1-R5" bar without being brittle to wording. Mirrors the
static-check style of ``test_minecraft_fork_maintenance.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = REPO_ROOT / "docs" / "decisions"
ADR = DECISIONS / "0010-bridge-protocol.md"
ADR_0005 = DECISIONS / "0005-skill-extension-point.md"
ADR_0002 = DECISIONS / "0002-auth-mode.md"
SUMMARY = DECISIONS / "0000-summary.md"
PACKAGE_JSON = REPO_ROOT / "package.json"

# The bridge contract anchors E1-R5 (#522 / ADR 0005) fixed. ADR 0010 chooses
# the transport but must not redefine these — it must repeat them verbatim.
BRIDGE_ENDPOINT = "/api/minecraft/bridge/ws"
BRIDGE_TOKEN_ENV = "MINECRAFT_BRIDGE_TOKEN"

# Envelope field set from ADR 0005 lines 39-54. The ADR 0010 contract must
# fix exactly this shape (request fields + response fields).
ENVELOPE_REQUEST_FIELDS = (
    "version",
    "request_id",
    "agent_id",
    "run_id",
    "simulation_id",
    "service",
    "method",
    "payload",
    "deadline_ms",
    "cost_context",
)
ENVELOPE_RESPONSE_FIELDS = ("request_id", "ok", "payload", "error", "retryable")

# Typed service names. ADR 0005 fixes the first six; later bridge issues extend
# the set with cost.gate, perception/action result, and code execution verbs.
# ADR 0010 must name all of them so the schemas have a fixed vocabulary.
ADR0005_SERVICE_NAMES = (
    "memory.recall",
    "memory.write",
    "management.review",
    "cost.reserve",
    "journal.event",
    "kill.status",
)
EXTENDED_SERVICE_NAMES = ("cost.gate", "perception.report", "action.result", "code.execute")

# The headed sections the issue scope requires (transport, envelope, versioning,
# auth, failure semantics), keyed to a stable lowercase substring.
REQUIRED_SECTIONS = {
    "non-technical summary": "non-technical summary",
    "transport decision": "transport",
    "message envelope": "envelope",
    "versioning": "versioning",
    "authentication": "authentication",
    "failure semantics": "failure semantics",
    "service names": "typed service names",
    "evidence": "evidence",
}

VERIFY_SCRIPT = "verify:bridge-protocol"


@pytest.fixture(scope="module")
def adr_text() -> str:
    assert ADR.is_file(), f"missing bridge protocol ADR: {ADR}"
    return ADR.read_text(encoding="utf-8")


def test_adr_exists_and_is_substantial(adr_text: str) -> None:
    # A protocol decision record is not a stub.
    assert len(adr_text) > 3000, "0010-bridge-protocol.md is too short to be the ADR"
    assert adr_text.lstrip().startswith("# Decision 0010:"), (
        "ADR must start with the '# Decision 0010:' title (ADR format)"
    )


def test_adr_follows_established_header_format(adr_text: str) -> None:
    """Same header block every other decision record uses, so the index and any
    future tooling can parse it uniformly."""
    head = adr_text[:600]
    assert re.search(r"^Status:", head, re.MULTILINE), "ADR needs a Status line"
    assert re.search(r"^Research date: 2026-", head, re.MULTILINE), (
        "ADR needs a 'Research date:' line like the sibling records"
    )
    assert re.search(r"^Related issue: #540, E4-1", head, re.MULTILINE), (
        "ADR must record 'Related issue: #540, E4-1'"
    )


@pytest.mark.parametrize("section", sorted(REQUIRED_SECTIONS))
def test_adr_covers_required_scope_sections(section: str, adr_text: str) -> None:
    """Issue scope requires transport, envelope, versioning, auth, and failure
    semantics to all be decided in this ADR."""
    needle = REQUIRED_SECTIONS[section]
    assert needle in adr_text.lower(), (
        f"0010-bridge-protocol.md is missing the {section!r} content ({needle!r})"
    )


def test_adr_picks_websocket_and_rejects_http_and_ipc(adr_text: str) -> None:
    """The decision must be explicit, not just mention the options: choose the
    authenticated WebSocket and explicitly reject plain HTTP and OS IPC."""
    lower = adr_text.lower()
    assert "websocket" in lower
    assert BRIDGE_ENDPOINT in adr_text, f"ADR must commit to the {BRIDGE_ENDPOINT} endpoint"
    # Rejected alternatives must be named so the decision is auditable.
    assert "http" in lower and "ipc" in lower, (
        "ADR must explicitly weigh and reject HTTP request/response and OS IPC"
    )
    assert "reject" in lower, "ADR must explicitly reject the alternatives"


def test_adr_endpoint_and_token_match_adr_0005(adr_text: str) -> None:
    """Consistency with E1-R5: the endpoint and auth env var are fixed by
    ADR 0005. ADR 0010 must not silently choose different ones."""
    adr0005 = ADR_0005.read_text(encoding="utf-8")
    for anchor in (BRIDGE_ENDPOINT, BRIDGE_TOKEN_ENV):
        assert anchor in adr0005, f"precondition: {anchor!r} should be in ADR 0005"
        assert anchor in adr_text, (
            f"0010 drifted from ADR 0005 — missing the agreed anchor {anchor!r}"
        )


@pytest.mark.parametrize("field", ENVELOPE_REQUEST_FIELDS + ENVELOPE_RESPONSE_FIELDS)
def test_adr_fixes_the_full_envelope_shape(field: str, adr_text: str) -> None:
    """Every envelope field ADR 0005 lines 39-54 named must reappear here so
    the shape (not the schema — that's E4-2) is unambiguously fixed."""
    assert f"`{field}`" in adr_text, (
        f"0010-bridge-protocol.md does not fix the envelope field `{field}`"
    )


def test_envelope_fields_are_consistent_with_adr_0005(adr_text: str) -> None:
    """Drift guard: the envelope ADR 0010 fixes must be the same one ADR 0005
    fixed. If a future edit changes one ADR's field set, this fails."""
    adr0005 = ADR_0005.read_text(encoding="utf-8")
    for field in ENVELOPE_REQUEST_FIELDS + ENVELOPE_RESPONSE_FIELDS:
        in_0005 = f"`{field}`" in adr0005
        in_0010 = f"`{field}`" in adr_text
        assert in_0005 == in_0010, (
            f"envelope field `{field}` disagreement: ADR0005={in_0005} "
            f"ADR0010={in_0010} — the two records must agree on the envelope"
        )


@pytest.mark.parametrize("service", ADR0005_SERVICE_NAMES + EXTENDED_SERVICE_NAMES)
def test_adr_names_the_typed_services(service: str, adr_text: str) -> None:
    """The bridge dispatches a closed set of typed services (no generic
    untyped Python bridge). ADR 0005's six plus later extensions must all be
    named so the schemas have a fixed vocabulary."""
    assert service in adr_text, (
        f"0010-bridge-protocol.md does not name the typed service {service!r}"
    )


def test_adr_states_versioning_policy(adr_text: str) -> None:
    """Versioning must be additive-compatible and reject an unknown major
    fail-closed; the schema registry itself is deferred to E4-2."""
    lower = adr_text.lower()
    assert "semver" in lower or "additive" in lower, (
        "ADR must state the additive-compatible / semver versioning policy"
    )
    assert "major" in lower, "ADR must state the unknown-major rejection rule"
    assert "e4-2" in lower, "ADR must defer the concrete schema/registry to E4-2"


def test_adr_states_fail_closed_auth_and_no_unauth_path(adr_text: str) -> None:
    """Ties to the epic security review: there must be no unauthenticated path
    to spend or in-world actions, and auth must fail closed. Also must
    cross-reference the offline-mode network rules (ADR 0002)."""
    lower = adr_text.lower()
    assert "fail-closed" in lower or "fail closed" in lower, (
        "ADR must state auth/gating is fail-closed"
    )
    assert "unauthenticated path" in lower and ("spend" in lower and "in-world" in lower), (
        "ADR must state there is no unauthenticated path to spend or in-world actions"
    )
    assert "0002-auth-mode.md" in adr_text, (
        "ADR must cross-reference ADR 0002 for offline-mode network rules"
    )


def test_adr_defers_reconnect_and_backpressure(adr_text: str) -> None:
    """Scope guard: reconnect/backpressure are E4-4/E4-5, not this ADR. The
    record must explicitly defer them rather than half-specifying them."""
    lower = adr_text.lower()
    assert "reconnect" in lower and "backpressure" in lower
    assert "e4-4" in lower, "ADR must defer reconnect/backpressure to E4-4"


def test_adr_cites_required_evidence(adr_text: str) -> None:
    """The Evidence section must link the sources the issue requires so the
    decision is traceable."""
    # The split keeps this robust to an 'Evidence' substring appearing earlier.
    _, _, evidence = adr_text.lower().rpartition("## evidence")
    assert evidence, "ADR is missing an '## Evidence' section"
    assert "core/main.py:181" in adr_text, (
        "Evidence must cite core/main.py:181 (the existing /ws endpoint)"
    )
    assert "0005-skill-extension-point.md" in adr_text
    assert "0002-auth-mode.md" in adr_text
    assert "minecraft-pivot-issue-plan.md" in evidence, "Evidence must link the plan (§5 E4-1)"


def test_adr_states_no_llm_runtime_path(adr_text: str) -> None:
    """E4-1 has no LLM runtime path; per the issue's validation note the ADR
    must say so explicitly and point at the nearest local smoke path."""
    lower = adr_text.lower()
    assert "no llm runtime path" in lower
    assert VERIFY_SCRIPT in adr_text, (
        "ADR must name the nearest local smoke path (pnpm verify:bridge-protocol)"
    )


def test_decision_index_links_the_new_record() -> None:
    """docs-sync: 0000-summary.md is the decision index; it must link 0010 so
    the record is discoverable and the index stays complete."""
    summary = SUMMARY.read_text(encoding="utf-8")
    assert "[0010: Bridge Protocol And Transport](0010-bridge-protocol.md)" in summary, (
        "0000-summary.md must list the 0010 decision record"
    )


def test_verify_script_is_wired_into_package_json() -> None:
    """The CI build check is only green if the script is actually wired — the
    backend-test job runs the whole tests/backend/ suite, and the named verify
    script gives a focused local smoke entrypoint that targets this module."""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    cmd = data.get("scripts", {}).get(VERIFY_SCRIPT)
    assert cmd, f"package.json is missing the {VERIFY_SCRIPT} script"
    assert "test_bridge_protocol_decision.py" in cmd, (
        f"{VERIFY_SCRIPT} must run this contract test module"
    )
