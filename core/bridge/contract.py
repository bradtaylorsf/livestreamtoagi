"""Versioned message contract for the Python<->Node bridge (issue #541, E4-2).

This module is the **single source of truth** for the bridge wire format. The
Python side validates with the Pydantic models defined here; the Node side
validates against the JSON Schema document exported from these same models
(:func:`export_json_schema`, committed at
``core/bridge/schemas/bridge-protocol.schema.json``). Because the JSON Schema is
*generated* from the Pydantic models — never hand-written — the two halves
cannot drift, which is the whole point of E4-2.

Everything here is fixed by ADR ``docs/decisions/0010-bridge-protocol.md``
(issue #540, E4-1), which is the authoritative decision record:

* §2 — the request/response envelope field set and semantics.
* §3 — versioning: additive-compatible, fail-closed on an unknown *major*.
* §5 — ``retryable`` defaults to not-retryable; ``request_id`` is the
  idempotency key for side-effecting calls.
* §6 — the bridge dispatches a **closed set** of typed ``service`` names; there
  is no generic "run arbitrary Python" verb.

**Vocabulary note (reconciles a known naming split).** Issue #541's scope text
lists ``memory.read``; ADR §6 — the source of truth — calls the same verb
``memory.recall``. This contract uses the ADR name ``memory.recall``
everywhere so the Node and Python sides share one vocabulary and the split is
closed rather than carried forward. The other initial verbs match the ADR
verbatim. ``bridge.ping`` is added because the ADR's "First proof:
``!bridgePing``" round-trip needs a schema before E4-3/E4-4 can prove the
channel; it is the only registry entry not in the ADR §6 table and is justified
solely by that ADR section.

There is no LLM runtime path in this issue: the contract is pure schema/data
plumbing with no model calls. The nearest local smoke path is the
dependency-free contract test ``pnpm verify:bridge-contract``
(``tests/backend/test_bridge_contract.py``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import models_json_schema

# Protocol semver. ADR §3: every message carries this; the contract is
# additive-compatible within a major and fail-closed across majors. 1.9 keeps
# the existing required `simulation_id` envelope field and documents that
# embodied supervisors provide it through runtime env so bridge-originated
# memory, action, errand, and journal events share one durable simulation id.
# Earlier 1.x peers remain wire-compatible because `is_supported_version` gates
# only on the major.
PROTOCOL_VERSION = "1.9"

# JSON Schema dialect the exported Node-side artifact targets. Pydantic v2
# emits 2020-12, so the committed schema and the Node validator agree.
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://livestreamtoagi.dev/bridge/bridge-protocol.schema.json"


# ── Version negotiation (ADR §3) ────────────────────────────────────────────


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a ``MAJOR.MINOR`` or ``MAJOR.MINOR.PATCH`` semver string.

    Raises :class:`ValueError` on anything malformed so callers can fail
    closed rather than guess (ADR §3).
    """
    if not isinstance(version, str):
        raise ValueError(f"version must be a string, got {type(version).__name__}")
    parts = version.split(".")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError(f"malformed protocol version: {version!r}")
    major, minor = int(parts[0]), int(parts[1])
    patch = int(parts[2]) if len(parts) == 3 else 0
    return major, minor, patch


SUPPORTED_MAJOR = parse_version(PROTOCOL_VERSION)[0]


def is_supported_version(version: str) -> bool:
    """Return whether *version* is wire-compatible with this peer.

    ADR §3 rule: the contract is additive-compatible *within* a major (any
    minor/patch of the same major is tolerated, in either direction, because
    new fields/verbs are optional and additive). An unknown — i.e. different —
    major is **not** supported, and a malformed version is treated as not
    supported. This is deliberately fail-closed: ambiguity is rejected, never
    guessed.
    """
    try:
        major, _minor, _patch = parse_version(version)
    except ValueError:
        return False
    return major == SUPPORTED_MAJOR


# ── Errors ──────────────────────────────────────────────────────────────────

# Stable, typed error codes used in the response envelope. Kept as constants so
# the Node side and tests reference the same strings.
ERR_UNSUPPORTED_VERSION = "unsupported_version"
ERR_UNSUPPORTED_SERVICE = "unsupported_service"
ERR_INVALID_PAYLOAD = "invalid_payload"


class UnsupportedServiceError(ValueError):
    """Raised when a ``service.method`` is not in the closed registry (ADR §6)."""

    def __init__(self, service: str, method: str) -> None:
        self.service = service
        self.method = method
        super().__init__(f"unsupported bridge service: {service}.{method}")


class BridgeError(BaseModel):
    """Typed error body carried by a failed response (ADR §2)."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable detail for logs/operators.")


# ── Envelope (ADR §2) ───────────────────────────────────────────────────────


class CostContext(BaseModel):
    """Cost-attribution hints (ADR §2 ``cost_context``).

    Carries enough metadata for E11 cost/kill controls to charge the right
    account: which model tier the call is for and which budget bucket it draws
    from. ``estimated_cost_usd`` is an optional pre-flight hint the cost gate
    may use; the authoritative number is computed Python-side.
    """

    model_config = ConfigDict(extra="forbid")
    agent_tier: Literal["conversation", "building", "errand", "filter"] = Field(
        description="Which model tier this call bills against (drives cost attribution)."
    )
    budget_bucket: str = Field(
        min_length=1,
        description="Budget account this draws from, e.g. 'daily-global' or 'weekly-vera'.",
    )
    estimated_cost_usd: float | None = Field(
        default=None, ge=0.0, description="Optional pre-flight spend estimate hint (USD)."
    )


class BridgeRequest(BaseModel):
    """Request envelope — Node->Python, or Python->Node for control messages.

    Field set is **exactly** ADR §2's request table; ``extra='forbid'`` so an
    unknown top-level field is rejected on both sides rather than silently
    ignored. ``payload`` is an opaque object here and is validated per-service
    via :data:`SERVICE_REGISTRY` / :func:`validate_request`.
    """

    model_config = ConfigDict(extra="forbid")
    version: str = Field(description="Protocol semver (ADR §3). Required on every message.")
    request_id: str = Field(
        min_length=1,
        description="Unique id; correlation + idempotency key for retries (ADR §5).",
    )
    agent_id: str = Field(
        min_length=1,
        description="Stable agent identity (e.g. 'vera'); a claim, not proof (ADR §4).",
    )
    run_id: str = Field(min_length=1, description="Run this message belongs to (attribution).")
    simulation_id: str = Field(
        min_length=1,
        description=(
            "Simulation this message belongs to (journal + cost). Embodied "
            "supervisors propagate this from LTAG_SIMULATION_ID / "
            "MINECRAFT_SIMULATION_ID so all bridge events share the run id."
        ),
    )
    service: str = Field(min_length=1, description="Typed service name (ADR §6 closed set).")
    method: str = Field(min_length=1, description="Method within the service.")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Service-specific body; schema owned per-verb below."
    )
    deadline_ms: int = Field(gt=0, description="Caller's hard deadline in milliseconds (ADR §5).")
    cost_context: CostContext = Field(description="Cost-attribution hints (ADR §2).")
    trace_id: str | None = Field(
        default=None,
        description=(
            "End-to-end correlation id for cross-language tracing (E4-7, #546). "
            "Optional and additive (ADR §3 minor bump, protocol 1.1): a 1.0 peer "
            "omits it. The server mints one when absent so a request is always "
            "traceable in both Node and Python logs by a single id."
        ),
    )


class BridgeResponse(BaseModel):
    """Response envelope — the other direction (ADR §2).

    ``retryable`` defaults to ``False``: per ADR §5 absence/ambiguity is
    treated as *not* retryable, so the default must encode the safe choice.
    """

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(
        min_length=1, description="Echoes the originating request's request_id."
    )
    ok: bool = Field(description="True = success, False = handled failure.")
    payload: dict[str, Any] | None = Field(
        default=None, description="Result body on success; schema owned per-verb below."
    )
    error: BridgeError | None = Field(default=None, description="Typed error when ok is False.")
    retryable: bool = Field(
        default=False, description="Whether the caller may safely retry (ADR §5)."
    )
    trace_id: str | None = Field(
        default=None,
        description=(
            "Echoes the request's correlation id (or the one the server minted "
            "when the request omitted it) so the same trace id appears on both "
            "halves of the round-trip (E4-7, #546). Optional/additive (ADR §3)."
        ),
    )


# ── Per-verb payload schemas ────────────────────────────────────────────────


class BridgePingRequest(BaseModel):
    """``bridge.ping`` — connectivity probe for the ADR's ``!bridgePing`` proof."""

    model_config = ConfigDict(extra="forbid")
    message: str = Field(description="Arbitrary text echoed back as 'pong'.")


class BridgePingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pong: str = Field(description="Echo of the request message.")


class MemoryRecallRequest(BaseModel):
    """``memory.recall`` — semantic/recall memory read (ADR §6; issue 'memory.read')."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, description="Natural-language recall query.")
    tier: Literal["recall", "core"] = Field(
        default="recall",
        description=(
            "Memory tier to read. 'recall' performs semantic recall; 'core' "
            "fetches the agent's Tier 1 core memory. Query remains required "
            "for additive compatibility and is ignored for tier='core'."
        ),
    )
    scope: Literal["agent", "shared", "world"] = Field(
        default="agent", description="Memory partition to search."
    )
    limit: int = Field(default=5, ge=1, le=50, description="Max results to return.")


class MemoryRecallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str = Field(description="Stable id of the recalled memory.")
    content: str = Field(description="Recalled memory text.")
    score: float = Field(ge=0.0, le=1.0, description="Similarity score.")


class MemoryRecallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[MemoryRecallResult] = Field(
        default_factory=list, description="Ranked recall hits (may be empty)."
    )
    formatted: str | None = Field(
        default=None,
        description="Formatted markdown returned by the recall memory manager.",
    )
    core_memory: str | None = Field(
        default=None,
        description="Core memory markdown returned by the core memory manager.",
    )


class MemoryWriteRequest(BaseModel):
    """``memory.write`` — persist a memory. Idempotent on the request_id (ADR §5)."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, description="Memory text to persist.")
    kind: Literal["observation", "reflection", "fact", "event"] = Field(
        description="Memory category."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Optional structured tags (free-form)."
    )


class MemoryWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str = Field(description="Id of the stored (or de-duplicated) memory.")


class ManagementReviewRequest(BaseModel):
    """``management.review`` — content-filter gate before broadcast (ADR §5)."""

    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, description="Agent whose output is under review.")
    text: str = Field(description="Candidate agent speech/output.")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Optional surrounding context for the filter."
    )


class ManagementReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["allow", "veto"] = Field(description="Filter decision.")
    reason: str = Field(description="Why the verdict was reached.")
    sanitized_text: str | None = Field(
        default=None, description="Cleaned text when the filter rewrote rather than vetoed."
    )


class CostGateRequest(BaseModel):
    """``cost.gate`` — check whether a spend/action is allowed (ADR §6)."""

    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, description="Agent requesting the spend.")
    action: str = Field(min_length=1, description="What the spend is for.")
    estimated_cost_usd: float = Field(ge=0.0, description="Estimated spend (USD).")


class CostGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool = Field(description="Whether the spend may proceed.")
    reason: str = Field(description="Why allowed/denied.")
    remaining_budget_usd: float = Field(
        description="Budget left in the relevant bucket after this decision."
    )


class KillStatusRequest(BaseModel):
    """``kill.status`` — query the global operator kill switch."""

    model_config = ConfigDict(extra="forbid")


class KillStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool = Field(description="Whether the global kill switch is active.")
    ttl_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Redis TTL for the kill switch key, or null when absent/unknown.",
    )
    reason: str | None = Field(
        default=None,
        description="Stable reason string when active or when status had to fail safe.",
    )


class Vec3(BaseModel):
    """3D coordinate in world space or a block cell."""

    model_config = ConfigDict(extra="forbid")
    x: float = Field(description="X coordinate.")
    y: float = Field(description="Y coordinate.")
    z: float = Field(description="Z coordinate.")


class PoseObservation(BaseModel):
    """Bot pose at the instant a perception snapshot was captured."""

    model_config = ConfigDict(extra="forbid")
    position: Vec3 = Field(description="Current bot position.")
    yaw: float = Field(description="Current yaw in radians.")
    pitch: float = Field(description="Current pitch in radians.")
    on_ground: bool = Field(description="Whether the bot is on the ground.")
    dimension: str = Field(min_length=1, description="Minecraft dimension id.")


class BlockObservation(BaseModel):
    """Observed block near the bot."""

    model_config = ConfigDict(extra="forbid")
    position: Vec3 = Field(description="Block cell position.")
    block_type: str = Field(min_length=1, description="Normalized block id.")


class EntityObservation(BaseModel):
    """Observed entity near the bot."""

    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, description="Stable entity id when available.")
    kind: Literal["player", "mob", "item", "object"] = Field(description="Entity category.")
    name: str | None = Field(default=None, description="Display/user name when known.")
    position: Vec3 = Field(description="Entity position.")
    distance: float = Field(ge=0.0, description="Distance from the observing bot.")


class InventoryItem(BaseModel):
    """Observed inventory stack."""

    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=0, description="Inventory slot index.")
    item_id: str = Field(min_length=1, description="Normalized item id.")
    count: int = Field(ge=0, description="Stack count.")


class InventoryObservation(BaseModel):
    """Observed inventory state."""

    model_config = ConfigDict(extra="forbid")
    items: list[InventoryItem] = Field(
        default_factory=list, description="Inventory stacks included in this snapshot."
    )
    equipment: dict[str, str | None] = Field(
        default_factory=dict, description="Equipment slot name -> normalized item id or null."
    )
    used_slots: int = Field(ge=0, description="Number of populated slots returned.")
    total_slots: int = Field(ge=0, description="Total known inventory slots.")


class PerceptionSnapshot(BaseModel):
    """Stable perception snapshot for E6 embodied decisions."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["perception_snapshot"] = Field(description="Snapshot discriminator.")
    pose: PoseObservation = Field(description="Current bot pose.")
    nearby_blocks: list[BlockObservation] = Field(
        default_factory=list, description="Blocks observed within radius."
    )
    entities: list[EntityObservation] = Field(
        default_factory=list, description="Entities observed within radius."
    )
    inventory: InventoryObservation = Field(description="Inventory state.")
    radius_blocks: float = Field(ge=0.0, description="Perception radius in blocks.")
    scope: Literal["pose", "nearby_blocks", "entities", "inventory", "all"] = Field(
        description="Requested snapshot scope."
    )
    include_air: bool = Field(description="Whether air blocks are included.")
    captured_tick: int | None = Field(
        default=None, ge=0, description="Minecraft/world tick when known."
    )


class PerceptionReportRequest(BaseModel):
    """``perception.report`` — bot-observed world state (schema fixed now, channel E4-6)."""

    model_config = ConfigDict(extra="forbid")
    observations: list[dict[str, Any]] = Field(
        description="Structured world observations from the bot."
    )


class PerceptionReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool = Field(description="Whether Python ingested the report.")


class ActionResultRequest(BaseModel):
    """``action.result`` — outcome of an in-world action (schema fixed now, channel E4-5)."""

    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, description="Id of the action this reports on.")
    status: Literal["success", "failure", "partial"] = Field(
        description="Terminal status of the action."
    )
    outcome_class: str | None = Field(
        default=None,
        min_length=1,
        description="Optional machine-readable outcome class such as interrupted or blocked.",
    )
    detail: str = Field(default="", description="Optional human-readable detail.")


class ActionResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool = Field(description="Whether Python recorded the result.")


class ErrandPollRequest(BaseModel):
    """``errand.poll`` — bot asks Python for its next dispatched task."""

    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, description="Stable id of the polling agent.")


class ErrandPollResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = Field(
        default=None, min_length=1, description="Dispatched task id, if any."
    )
    task: str | None = Field(
        default=None, min_length=1, description="Natural-language errand text."
    )
    from_agent: str | None = Field(
        default=None, min_length=1, description="Agent that dispatched the errand."
    )
    dispatched_at_ms: int | None = Field(
        default=None, ge=0, description="Unix epoch milliseconds when the task was queued."
    )
    urgency: Literal["when_free", "now"] | None = Field(
        default=None, description="Dispatch urgency, or null when no task is pending."
    )


class ErrandStepResult(BaseModel):
    """One terminal in-world action outcome within an Alpha errand."""

    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, description="Step action id from the errand plan.")
    status: Literal["success", "failure", "partial"] = Field(
        description="Verified terminal status reported by the action surface."
    )
    detail: str = Field(default="", description="Human-readable verifier detail.")


class ErrandCompleteRequest(BaseModel):
    """``errand.complete`` — Alpha reports a verified errand outcome.

    E7-3 uses this verb to connect the embodied action result back to the
    dispatcher: ``symbol`` is Alpha's non-verbal ✓/✗/? summary, while
    ``step_results`` preserves the per-action verified outcome.
    """

    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, description="Dispatched errand task id.")
    status: Literal["success", "failure", "partial"] = Field(
        description="Overall verified errand status."
    )
    symbol: Literal["✓", "✗", "?"] = Field(
        description="Alpha's non-verbal outcome symbol: success, failure, or confused."
    )
    detail: str = Field(default="", description="Human-readable errand outcome detail.")
    step_results: list[ErrandStepResult] = Field(
        default_factory=list, description="Verified terminal results for each errand step."
    )


class ErrandCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool = Field(description="Whether Python recorded the errand completion.")


class CodeExecuteRequest(BaseModel):
    """``code.execute`` — run code in the existing Docker/gVisor sandbox."""

    model_config = ConfigDict(extra="forbid")
    language: Literal["python", "javascript"] = Field(
        description="Runtime language supported by ExecuteCodeTool."
    )
    code: str = Field(min_length=1, description="Source code to run in the sandbox.")
    timeout: int | None = Field(
        default=None,
        ge=1,
        le=120,
        description="Optional max execution time in seconds; omitted uses the tool default.",
    )


class CodeExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "error", "rejected"] = Field(
        description="Sandbox result state returned by ExecuteCodeTool."
    )
    stdout: str | None = Field(default=None, description="Captured standard output.")
    stderr: str | None = Field(default=None, description="Captured standard error.")
    reason: str | None = Field(default=None, description="Error or rejection reason.")
    exit_code: int | None = Field(default=None, description="Process exit code when run.")
    execution_time_ms: int | None = Field(
        default=None, description="Elapsed execution time in milliseconds."
    )


class DirectorGateRequest(BaseModel):
    """``director.gate`` — Director V2 prompt eligibility check for Mindcraft."""

    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, description="Bot requesting prompt permission.")
    event_kind: Literal["chat", "action_result", "perception_event"] = Field(
        description="Kind of scene event that would trigger a Mindcraft prompt."
    )
    event_text: str = Field(description="Human-readable chat/action/perception text.")
    source_agent: str | None = Field(
        default=None,
        description="Agent or speaker that caused the event, when known.",
    )
    mentions: list[str] = Field(
        default_factory=list,
        description="Directly addressed agent ids parsed by the caller.",
    )
    position: Vec3 | None = Field(
        default=None,
        description="Best-known local Minecraft position for spatial scheduling.",
    )
    scene_hint: str | None = Field(
        default=None,
        description="Optional caller-side grouping hint for batched messages.",
    )
    available_tools: list[str] = Field(
        default_factory=list,
        description="Mindcraft action/tool affordances available to the selected prompt.",
    )


class DirectorBuildMacro(BaseModel):
    """Director-scheduled build macro context for one prompt verdict."""

    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(description="Scene id for this build macro decision.")
    plan_id: str | None = Field(default=None, description="Director build plan id.")
    owner: str | None = Field(default=None, description="Agent that owns the build plan.")
    role: Literal["planner_owner", "support"] = Field(
        description="Whether this agent owns the plan or supports it."
    )
    support_role: Literal["gather", "clear", "guard", "converse"] | None = Field(
        default=None,
        description="Support role for non-owner agents.",
    )
    support_task: str | None = Field(
        default=None,
        description="Short support instruction for non-owner agents.",
    )
    reason: str = Field(description="Build macro scheduling reason.")
    granted: bool = Field(
        default=False,
        description="Whether the agent may invoke !planAndBuild for this verdict.",
    )
    status: str | None = Field(default=None, description="Current Director build plan status.")
    cache_key: str | None = Field(default=None, description="Stable build-goal cache key.")


class DirectorGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: bool = Field(description="Whether this bot may enter the prompt path.")
    turn_kind: Literal["speaker", "planner"] | None = Field(
        default=None,
        description="Selected turn class, or null when suppressed/bypassed.",
    )
    reason: str = Field(description="Selection or bypass reason.")
    suppression_reason: str | None = Field(
        default=None,
        description="Why this bot was suppressed, when selected is false.",
    )
    scene_id: str = Field(description="Director V2 scene id used for the decision.")
    scene_digest: str = Field(description="Compact scene context for the selected prompt.")
    role: str = Field(description="Role assigned to the selected prompt context.")
    local_observations: dict[str, Any] = Field(
        default_factory=dict,
        description="Local scene observations to include in selected prompt context.",
    )
    granted_tools: list[str] = Field(
        default_factory=list,
        description="Action/tool affordances granted to this selected prompt.",
    )
    build_macro: DirectorBuildMacro | None = Field(
        default=None,
        description="Director-scheduled build macro ownership/support context.",
    )
    queue_depth: int = Field(ge=0, description="Director gate decision queue depth.")
    suppressed_agents: list[str] = Field(
        default_factory=list,
        description="Known agents suppressed by this scene decision.",
    )


# ── Service registry (ADR §6 closed set) ────────────────────────────────────

# Maps "<service>.<method>" -> (request payload model, response payload model).
# This is the *closed* dispatch set: anything not here is rejected with a typed
# unsupported_service error. Keys are ADR §6 names, plus bridge.ping for the
# ADR's first-proof round-trip and errand.* for the E7 Alpha dispatch slice.
# Other ADR §6 services (cost.reserve, journal.event) are intentionally out of
# E4-2's scope — their schemas land with their owning issues; the frozen #541
# initial verbs remain tracked separately in INITIAL_VERBS.
SERVICE_REGISTRY: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "bridge.ping": (BridgePingRequest, BridgePingResponse),
    "memory.recall": (MemoryRecallRequest, MemoryRecallResponse),
    "memory.write": (MemoryWriteRequest, MemoryWriteResponse),
    "management.review": (ManagementReviewRequest, ManagementReviewResponse),
    "cost.gate": (CostGateRequest, CostGateResponse),
    "kill.status": (KillStatusRequest, KillStatusResponse),
    "perception.report": (PerceptionReportRequest, PerceptionReportResponse),
    "action.result": (ActionResultRequest, ActionResultResponse),
    "errand.poll": (ErrandPollRequest, ErrandPollResponse),
    "errand.complete": (ErrandCompleteRequest, ErrandCompleteResponse),
    "code.execute": (CodeExecuteRequest, CodeExecuteResponse),
    "director.gate": (DirectorGateRequest, DirectorGateResponse),
}

# The six initial verbs #541 requires schemas for (ADR §6 names; the issue's
# 'memory.read' is ADR 'memory.recall'). bridge.ping is extra, not in this set.
INITIAL_VERBS: tuple[str, ...] = (
    "memory.recall",
    "memory.write",
    "management.review",
    "cost.gate",
    "perception.report",
    "action.result",
)


def service_key(service: str, method: str) -> str:
    """Canonical registry key for a service/method pair."""
    return f"{service}.{method}"


def get_models(service: str, method: str) -> tuple[type[BaseModel], type[BaseModel]]:
    """Resolve the (request, response) payload models for a verb.

    Raises :class:`UnsupportedServiceError` for anything outside the closed
    set so the dispatcher fails closed (ADR §6) instead of treating an unknown
    verb as a generic passthrough.
    """
    try:
        return SERVICE_REGISTRY[service_key(service, method)]
    except KeyError:
        raise UnsupportedServiceError(service, method) from None


def validate_request(env: BridgeRequest) -> BaseModel:
    """Validate a request envelope's payload against its per-verb schema.

    Returns the parsed payload model instance. Raises
    :class:`UnsupportedServiceError` for an unknown verb and
    :class:`pydantic.ValidationError` for a payload that does not match the
    verb's schema.
    """
    request_model, _response_model = get_models(env.service, env.method)
    return request_model.model_validate(env.payload)


def validate_response(env: BridgeResponse, *, service: str, method: str) -> BaseModel | None:
    """Validate a response envelope against the verb identified by *service*/*method*.

    The response envelope does not carry the verb (it is correlated to its
    request by ``request_id``), so the caller passes the verb it issued. On a
    successful response (``ok=True``) the payload is validated against the
    verb's response schema and the parsed model is returned. On a handled
    failure (``ok=False``) the envelope must carry a typed ``error`` and no
    payload model is returned.
    """
    _request_model, response_model = get_models(service, method)
    if env.ok:
        if env.payload is None:
            raise ValueError("successful response (ok=True) must carry a payload")
        return response_model.model_validate(env.payload)
    if env.error is None:
        raise ValueError("failed response (ok=False) must carry a typed error")
    return None


# ── Typed response helpers (used by the E4-3 server; verified by the test) ───


def make_error_response(
    request_id: str, code: str, message: str, *, retryable: bool = False
) -> BridgeResponse:
    """Build a contract-valid failure response with a typed error."""
    return BridgeResponse(
        request_id=request_id,
        ok=False,
        error=BridgeError(code=code, message=message),
        retryable=retryable,
    )


def unsupported_version_response(request_id: str, version: str) -> BridgeResponse:
    """The exact fail-closed response ADR §3 mandates for an unknown major.

    ``ok: false``, ``error.code = "unsupported_version"``, ``retryable: false``.
    """
    return make_error_response(
        request_id,
        ERR_UNSUPPORTED_VERSION,
        f"unsupported protocol version {version!r}; this peer speaks {PROTOCOL_VERSION}",
        retryable=False,
    )


# ── JSON Schema export (the Node-side artifact) ─────────────────────────────

# Every model that must appear in the bundled $defs. Order is fixed so the
# generated document is deterministic (the drift test depends on stability).
_SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    BridgeError,
    CostContext,
    BridgeRequest,
    BridgeResponse,
    BridgePingRequest,
    BridgePingResponse,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryRecallResponse,
    MemoryWriteRequest,
    MemoryWriteResponse,
    ManagementReviewRequest,
    ManagementReviewResponse,
    CostGateRequest,
    CostGateResponse,
    KillStatusRequest,
    KillStatusResponse,
    Vec3,
    PoseObservation,
    BlockObservation,
    EntityObservation,
    InventoryItem,
    InventoryObservation,
    PerceptionSnapshot,
    PerceptionReportRequest,
    PerceptionReportResponse,
    ActionResultRequest,
    ActionResultResponse,
    ErrandPollRequest,
    ErrandPollResponse,
    ErrandStepResult,
    ErrandCompleteRequest,
    ErrandCompleteResponse,
    CodeExecuteRequest,
    CodeExecuteResponse,
    DirectorGateRequest,
    DirectorGateResponse,
)


def export_json_schema() -> dict[str, Any]:
    """Build the single bundled JSON Schema document the Node side validates against.

    One Draft 2020-12 document with a ``$defs`` entry for every envelope and
    per-verb payload model (generated from the Pydantic models, so it cannot
    drift), plus a ``services`` map from ``service.method`` to the
    request/response ``$defs`` refs so the Node client can pick the right
    payload schema for a verb.
    """
    _key_map, defs_doc = models_json_schema(
        [(model, "validation") for model in _SCHEMA_MODELS],
        ref_template="#/$defs/{model}",
    )
    defs = defs_doc.get("$defs", {})

    services = {
        key: {
            "request": f"#/$defs/{request_model.__name__}",
            "response": f"#/$defs/{response_model.__name__}",
        }
        for key, (request_model, response_model) in SERVICE_REGISTRY.items()
    }

    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": SCHEMA_ID,
        "title": "Livestream-to-AGI bridge protocol",
        "description": (
            "Generated from core/bridge/contract.py — do not edit by hand. "
            "Run scripts/export_bridge_schemas.py to regenerate."
        ),
        "protocolVersion": PROTOCOL_VERSION,
        "envelopes": {
            "request": "#/$defs/BridgeRequest",
            "response": "#/$defs/BridgeResponse",
        },
        "services": services,
        "$defs": defs,
    }
