"""Contract test for the versioned bridge message schema (issue #541, E4-2).

E4-2's acceptance bar: *schemas committed; a contract test validates both
directions against fixtures*. "Both directions" = Node->Python **request** and
Python->Node **response**; "both sides" = the Python Pydantic models *and* the
committed JSON Schema the Node side validates against. This module checks all
four combinations against committed static fixtures, plus the guards that keep
the contract honest:

* every valid fixture is accepted by **both** the Pydantic models and the
  committed JSON Schema (via ``jsonschema``);
* every invalid fixture is rejected by **both** — and its *envelope* is
  independently valid, so the rejection genuinely exercises the per-verb
  payload schema (not just envelope coverage giving false confidence);
* the committed schema equals a fresh export — Pydantic is the single source
  of truth, so the Node-side artifact cannot silently drift;
* version negotiation is fail-closed on an unknown major (ADR §3);
* the registry is exactly the six initial verbs from #541 (+ ``bridge.ping``)
  and uses ADR §6 names only — including the ``memory.read`` ->
  ``memory.recall`` reconciliation the issue text and the ADR disagreed on.

Dependency-free by design: pure file reads + ``pydantic`` + ``jsonschema``.
No Node, no Docker, no network, no LLM — it runs headless in the existing
``backend-test`` CI job and is the nearest local smoke path for this issue
(which has no LLM runtime path).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from core.bridge import contract as c

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "bridge"
COMMITTED_SCHEMA = REPO_ROOT / "core" / "bridge" / "schemas" / "bridge-protocol.schema.json"

# ADR docs/decisions/0010-bridge-protocol.md §2 fixes these exact envelope
# fields. The Pydantic models must match this set verbatim or Node and Python
# disagree on the wire shape.
# `trace_id` is the E4-7 (#546) additive correlation field: optional, default
# None, a protocol 1.1 minor bump (ADR §3 additive-compatible) — not an ADR §2
# rename, so the rest of the set stays verbatim.
ADR_REQUEST_FIELDS = {
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
    "trace_id",
}
ADR_RESPONSE_FIELDS = {"request_id", "ok", "payload", "error", "retryable", "trace_id"}

# ADR §6 closed set of typed service names. The registry must be a subset of
# this (plus bridge.ping, which the ADR's "First proof: !bridgePing" names but
# does not table). Anything else would be an out-of-contract verb.
ADR_SERVICE_NAMES = {
    "memory.recall",
    "memory.write",
    "management.review",
    "cost.reserve",
    "cost.gate",
    "journal.event",
    "kill.status",
    "perception.report",
    "action.result",
}
ALLOWED_REGISTRY_KEYS = ADR_SERVICE_NAMES | {"bridge.ping"}

# The six initial verbs #541 scopes (issue 'memory.read' == ADR 'memory.recall').
ISSUE_INITIAL_VERBS = {
    "memory.recall",
    "memory.write",
    "management.review",
    "cost.gate",
    "perception.report",
    "action.result",
}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def committed_schema() -> dict[str, Any]:
    assert COMMITTED_SCHEMA.is_file(), (
        f"missing committed Node-side schema {COMMITTED_SCHEMA} — run "
        "`.venv/bin/python scripts/export_bridge_schemas.py`"
    )
    return _load(COMMITTED_SCHEMA)


def _subschema(committed: dict[str, Any], ref_name: str) -> dict[str, Any]:
    """A standalone JSON Schema that resolves a single ``$defs`` entry.

    Reuses the *committed* ``$defs`` (the actual Node-side artifact) so the
    test validates against what Node would, not against a Python re-derivation.
    """
    return {
        "$schema": c.JSON_SCHEMA_DIALECT,
        "$defs": committed["$defs"],
        "$ref": f"#/$defs/{ref_name}",
    }


def _jsonschema_ok(committed: dict[str, Any], ref_name: str, instance: Any) -> bool:
    validator = jsonschema.Draft202012Validator(_subschema(committed, ref_name))
    return validator.is_valid(instance)


# Verb -> (request payload model name, response payload model name) in $defs.
VERB_KEYS = sorted(c.SERVICE_REGISTRY)
DIRECTIONS = ("request", "response")


# ── Fixture coverage ────────────────────────────────────────────────────────


def test_every_registry_verb_has_all_four_fixtures() -> None:
    """Both directions, valid + invalid, for every verb — no silent gaps."""
    for key in c.SERVICE_REGISTRY:
        for direction in DIRECTIONS:
            for kind in ("valid", "invalid"):
                f = FIXTURES / key / f"{direction}.{kind}.json"
                assert f.is_file(), f"missing fixture {f}"


def test_initial_issue_verbs_are_all_in_the_registry() -> None:
    missing = ISSUE_INITIAL_VERBS - set(c.SERVICE_REGISTRY)
    assert not missing, f"#541 initial verbs missing from the registry: {sorted(missing)}"
    assert set(c.INITIAL_VERBS) == ISSUE_INITIAL_VERBS, (
        "contract.INITIAL_VERBS must be exactly the six verbs #541 scopes"
    )


# ── Both directions / both sides: valid fixtures accepted ───────────────────


@pytest.mark.parametrize("key", VERB_KEYS)
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_valid_fixture_accepted_by_pydantic_and_jsonschema(
    key: str, direction: str, committed_schema: dict[str, Any]
) -> None:
    service, method = key.split(".", 1)
    request_model, response_model = c.SERVICE_REGISTRY[key]
    env = _load(FIXTURES / key / f"{direction}.valid.json")

    if direction == "request":
        # Python side: envelope parses and the payload matches the verb schema.
        parsed = c.BridgeRequest.model_validate(env)
        payload_model = c.validate_request(parsed)
        assert payload_model.__class__ is request_model
        # Node side: envelope and payload both validate against the committed
        # JSON Schema (this is the "both sides" half of the check).
        assert _jsonschema_ok(committed_schema, "BridgeRequest", env)
        assert _jsonschema_ok(committed_schema, request_model.__name__, env["payload"])
    else:
        parsed_resp = c.BridgeResponse.model_validate(env)
        payload_model = c.validate_response(parsed_resp, service=service, method=method)
        assert payload_model is not None
        assert payload_model.__class__ is response_model
        assert _jsonschema_ok(committed_schema, "BridgeResponse", env)
        assert _jsonschema_ok(committed_schema, response_model.__name__, env["payload"])


# ── Both directions / both sides: invalid fixtures rejected ─────────────────


@pytest.mark.parametrize("key", VERB_KEYS)
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_invalid_fixture_rejected_by_pydantic_and_jsonschema(
    key: str, direction: str, committed_schema: dict[str, Any]
) -> None:
    service, method = key.split(".", 1)
    request_model, response_model = c.SERVICE_REGISTRY[key]
    env = _load(FIXTURES / key / f"{direction}.invalid.json")

    if direction == "request":
        # The envelope itself is valid — proving the rejection comes from the
        # per-verb payload schema, not generic envelope coverage. This is what
        # makes the per-verb contract real rather than a false-positive.
        parsed = c.BridgeRequest.model_validate(env)
        assert _jsonschema_ok(committed_schema, "BridgeRequest", env), (
            "invalid-payload fixture must keep a valid envelope so the test "
            "exercises the per-verb schema"
        )
        with pytest.raises(ValidationError):
            c.validate_request(parsed)
        assert not _jsonschema_ok(committed_schema, request_model.__name__, env["payload"])
    else:
        parsed_resp = c.BridgeResponse.model_validate(env)
        assert _jsonschema_ok(committed_schema, "BridgeResponse", env)
        with pytest.raises((ValidationError, ValueError)):
            c.validate_response(parsed_resp, service=service, method=method)
        assert not _jsonschema_ok(committed_schema, response_model.__name__, env["payload"])


# ── Pydantic <-> JSON Schema <-> ADR are one contract ───────────────────────


def test_committed_schema_equals_fresh_export(committed_schema: dict[str, Any]) -> None:
    """Pydantic is the source of truth; the committed Node artifact must not
    drift. Structural equality plus exact-text equality (same recipe as
    scripts/export_bridge_schemas.py) catches both content and formatting
    staleness."""
    fresh = c.export_json_schema()
    assert committed_schema == fresh, (
        "committed bridge schema is stale — run `.venv/bin/python scripts/export_bridge_schemas.py`"
    )
    expected_text = json.dumps(fresh, indent=2, sort_keys=True) + "\n"
    assert COMMITTED_SCHEMA.read_text(encoding="utf-8") == expected_text, (
        "committed schema formatting drifted from the deterministic export recipe"
    )


def test_schema_is_draft_2020_12_with_a_complete_service_map(
    committed_schema: dict[str, Any],
) -> None:
    assert committed_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert committed_schema["protocolVersion"] == c.PROTOCOL_VERSION
    defs = committed_schema["$defs"]
    # Envelope refs resolve.
    for ref in committed_schema["envelopes"].values():
        assert ref.split("/")[-1] in defs
    # Service map matches the registry and every ref resolves to a real $def.
    assert set(committed_schema["services"]) == set(c.SERVICE_REGISTRY)
    for key, refs in committed_schema["services"].items():
        req_model, resp_model = c.SERVICE_REGISTRY[key]
        assert refs["request"] == f"#/$defs/{req_model.__name__}"
        assert refs["response"] == f"#/$defs/{resp_model.__name__}"
        assert req_model.__name__ in defs
        assert resp_model.__name__ in defs


def test_envelope_models_match_adr_field_set() -> None:
    """Drift guard tying the Pydantic envelopes to ADR §2 (+ the E4-7
    additive `trace_id`) verbatim."""
    assert set(c.BridgeRequest.model_fields) == ADR_REQUEST_FIELDS
    assert set(c.BridgeResponse.model_fields) == ADR_RESPONSE_FIELDS


def test_trace_id_is_optional_and_additive_on_both_envelopes(
    committed_schema: dict[str, Any],
) -> None:
    """E4-7 (#546): `trace_id` is an OPTIONAL string on both envelopes — a
    purely additive 1.1 change. It must (a) default to None on the Pydantic
    models, (b) appear in the committed Node-side schema, and (c) NOT be in
    either envelope's `required` list, so a 1.0 peer that omits it still
    validates on both sides (ADR §3 additive-compatible)."""
    # (a) Pydantic: present, optional, defaults to None.
    for model in (c.BridgeRequest, c.BridgeResponse):
        assert "trace_id" in model.model_fields
        assert model.model_fields["trace_id"].default is None

    # A request/response with no trace_id still parses (additive, not required).
    req = c.BridgeRequest.model_validate(_load(FIXTURES / "bridge.ping" / "request.valid.json"))
    assert req.trace_id is None
    assert c.BridgeResponse(request_id="r", ok=True, payload={"pong": "x"}).trace_id is None

    # An explicit trace_id round-trips through the envelope (extra='forbid' so
    # it only passes because it is a *declared* field, not silently ignored).
    assert (
        c.BridgeRequest.model_validate(
            _load(FIXTURES / "bridge.ping" / "request.valid.json") | {"trace_id": "trace-abc"}
        ).trace_id
        == "trace-abc"
    )

    # (b)/(c) Committed Node-side schema: present on both, required on neither.
    defs = committed_schema["$defs"]
    for env_name in ("BridgeRequest", "BridgeResponse"):
        assert "trace_id" in defs[env_name]["properties"], env_name
        assert "trace_id" not in defs[env_name].get("required", []), env_name


# ── Versioning (ADR §3, fail-closed) ────────────────────────────────────────


def test_protocol_version_is_self_consistent() -> None:
    # 1.1: E4-7 (#546) added the optional `trace_id` correlation field to both
    # envelopes — an additive minor bump (ADR §3), same major as 1.0.
    assert c.PROTOCOL_VERSION == "1.1"
    assert c.is_supported_version(c.PROTOCOL_VERSION)
    assert c.parse_version(c.PROTOCOL_VERSION) == (1, 1, 0)


@pytest.mark.parametrize("version", ["1.0", "1.4", "1.0.9", "1.99.99"])
def test_additive_same_major_versions_supported(version: str) -> None:
    """ADR §3: new optional fields/verbs are minor/patch and must not break a
    peer — any same-major version is wire-compatible in either direction."""
    assert c.is_supported_version(version)


@pytest.mark.parametrize("version", ["2.0", "0.9", "3.1.4", "", "abc", "1", "1.x", "v1.0"])
def test_unknown_major_or_malformed_rejected_fail_closed(version: str) -> None:
    """ADR §3: an unknown major (or anything unparseable) is rejected, not
    guessed — the safe, fail-closed default."""
    assert not c.is_supported_version(version)


def test_unsupported_version_response_is_the_adr_mandated_shape() -> None:
    """ADR §3 mandates the exact failure: ok=false, code=unsupported_version,
    retryable=false — and it must itself be a contract-valid response."""
    resp = c.unsupported_version_response("req-xyz", "2.0")
    assert isinstance(resp, c.BridgeResponse)
    assert resp.request_id == "req-xyz"
    assert resp.ok is False
    assert resp.retryable is False
    assert resp.error is not None
    assert resp.error.code == c.ERR_UNSUPPORTED_VERSION
    # Round-trips through the response envelope schema (extra='forbid' etc.).
    c.BridgeResponse.model_validate(resp.model_dump())


@pytest.mark.parametrize("bad", ["", "1", "1.x", "x.y", "1.2.3.4", "-1.0"])
def test_parse_version_raises_on_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        c.parse_version(bad)


# ── Closed registry & ADR §6 vocabulary (the naming reconciliation) ─────────


def test_registry_is_closed_and_uses_adr_names_only() -> None:
    keys = set(c.SERVICE_REGISTRY)
    assert ISSUE_INITIAL_VERBS.issubset(keys), "all six #541 verbs must be registered"
    unexpected = keys - ALLOWED_REGISTRY_KEYS
    assert not unexpected, (
        f"registry has out-of-contract verbs not in ADR §6 (+bridge.ping): {sorted(unexpected)}"
    )


def test_memory_read_is_reconciled_to_memory_recall() -> None:
    """Issue #541 text says ``memory.read``; ADR §6 (source of truth) says
    ``memory.recall``. The split must be *closed* — recall registered, the
    issue's alias absent — not carried forward as a second name."""
    assert "memory.recall" in c.SERVICE_REGISTRY
    assert "memory.read" not in c.SERVICE_REGISTRY


def test_unknown_service_fails_closed_with_typed_error() -> None:
    with pytest.raises(c.UnsupportedServiceError):
        c.get_models("totally", "madeup")
    bad_env = c.BridgeRequest.model_validate(
        _load(FIXTURES / "bridge.ping" / "request.valid.json")
        | {"service": "danger", "method": "exec"}
    )
    with pytest.raises(c.UnsupportedServiceError):
        c.validate_request(bad_env)
