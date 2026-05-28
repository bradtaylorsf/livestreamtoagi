"""Director V2 parity inventory for backend tools."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ToolClassification = Literal[
    "callable_now",
    "approval_gated",
    "deferred",
    "retired",
    "replaced_by_minecraft",
]

ToolCategory = Literal[
    "alpha",
    "alliance",
    "audience",
    "character",
    "civilization",
    "code",
    "economy",
    "email",
    "journal_image",
    "memory",
    "messaging",
    "revenue",
    "self_mod",
    "social",
    "task",
    "tilemap",
    "web",
    "world_state",
]


@dataclass(frozen=True, slots=True)
class ToolParityEntry:
    """A single Director V2 tool parity decision."""

    name: str
    module: str
    category: ToolCategory
    classification: ToolClassification
    rationale: str
    linked_issue: str | None = None
    minecraft_replacement: str | None = None


TOOL_PARITY: dict[str, ToolParityEntry] = {
    "dispatch_alpha": ToolParityEntry(
        name="dispatch_alpha",
        module="tools.alpha_dispatch",
        category="alpha",
        classification="callable_now",
        rationale="Alpha errands already route through the backend bridge, kill switch, and LLM client.",
    ),
    "get_audience_status": ToolParityEntry(
        name="get_audience_status",
        module="tools.audience",
        category="audience",
        classification="callable_now",
        rationale="Read-only audience snapshot remains useful context for Minecraft scenes.",
    ),
    "send_chat_message": ToolParityEntry(
        name="send_chat_message",
        module="tools.audience_tools",
        category="audience",
        classification="approval_gated",
        rationale="Public chat output must not bypass Management or the human approval policy.",
    ),
    "create_poll": ToolParityEntry(
        name="create_poll",
        module="tools.audience_tools",
        category="audience",
        classification="approval_gated",
        rationale="Audience polls are public interaction requests and need explicit approval in Director V2.",
    ),
    "get_poll_results": ToolParityEntry(
        name="get_poll_results",
        module="tools.audience_tools",
        category="audience",
        classification="callable_now",
        rationale="Poll result reads are internal context and do not publish anything.",
    ),
    "propose_character": ToolParityEntry(
        name="propose_character",
        module="tools.character_tools",
        category="character",
        classification="callable_now",
        rationale="Character applications stay internal and still flow through the existing voting lifecycle.",
    ),
    "vote_character": ToolParityEntry(
        name="vote_character",
        module="tools.character_tools",
        category="character",
        classification="callable_now",
        rationale="Character votes are internal governance actions with existing validation.",
    ),
    "execute_code": ToolParityEntry(
        name="execute_code",
        module="tools.code_execution",
        category="code",
        classification="deferred",
        rationale="Embodied code execution needs the dedicated bridge and sandbox exposure work.",
        linked_issue="#560",
    ),
    "transfer_budget": ToolParityEntry(
        name="transfer_budget",
        module="tools.economy_tools",
        category="economy",
        classification="callable_now",
        rationale="Internal agent-to-agent budget transfers preserve the existing economy manager boundary.",
    ),
    "view_account": ToolParityEntry(
        name="view_account",
        module="tools.economy_tools",
        category="economy",
        classification="callable_now",
        rationale="Account balance reads are internal context for budgeting scenes.",
    ),
    "generate_journal_image": ToolParityEntry(
        name="generate_journal_image",
        module="tools.journal_image_tool",
        category="journal_image",
        classification="deferred",
        rationale="Journal illustration generation remains valid but is owned by the journal-image preservation work.",
        linked_issue="#583",
    ),
    "recall_memory": ToolParityEntry(
        name="recall_memory",
        module="tools.memory_tools",
        category="memory",
        classification="callable_now",
        rationale="Tier 2 recall is still a backend memory read and keeps the three-tier memory boundary.",
        linked_issue="#551/#552/#708",
    ),
    "retrieve_transcript": ToolParityEntry(
        name="retrieve_transcript",
        module="tools.memory_tools",
        category="memory",
        classification="callable_now",
        rationale="Tier 3 transcript lookup remains a read-only backend memory operation.",
        linked_issue="#551/#552/#708",
    ),
    "update_core_memory": ToolParityEntry(
        name="update_core_memory",
        module="tools.memory_tools",
        category="memory",
        classification="callable_now",
        rationale="Tier 1 core writes preserve existing section and cross-agent writer checks.",
        linked_issue="#551/#552/#708",
    ),
    "send_message": ToolParityEntry(
        name="send_message",
        module="tools.messaging",
        category="messaging",
        classification="callable_now",
        rationale="Internal agent messaging is not public external communication and remains event-bus backed.",
    ),
    "get_revenue_status": ToolParityEntry(
        name="get_revenue_status",
        module="tools.revenue_tools",
        category="revenue",
        classification="callable_now",
        rationale="Read-only financial health context remains valid for Sentinel and Vera.",
    ),
    "draft_social_post": ToolParityEntry(
        name="draft_social_post",
        module="tools.revenue_tools",
        category="social",
        classification="approval_gated",
        rationale="Social publishing stays human-review-only via the existing draft artifact path.",
    ),
    "draft_email": ToolParityEntry(
        name="draft_email",
        module="tools.revenue_tools",
        category="email",
        classification="approval_gated",
        rationale="Outbound email stays human-review-only via the existing draft artifact path.",
    ),
    "check_post_performance": ToolParityEntry(
        name="check_post_performance",
        module="tools.revenue_tools",
        category="social",
        classification="callable_now",
        rationale="Engagement lookup is read-only and does not publish external content.",
    ),
    "check_email_responses": ToolParityEntry(
        name="check_email_responses",
        module="tools.revenue_tools",
        category="email",
        classification="callable_now",
        rationale="Email response lookup is read-only and does not send external communication.",
    ),
    "propose_self_modification": ToolParityEntry(
        name="propose_self_modification",
        module="tools.self_modification",
        category="self_mod",
        classification="approval_gated",
        rationale="Self-modification only creates a human-review proposal and must not auto-apply changes.",
    ),
    "view_evolution_log": ToolParityEntry(
        name="view_evolution_log",
        module="tools.self_modification",
        category="self_mod",
        classification="callable_now",
        rationale="Evolution log reads are internal and preserve the existing self-modification audit trail.",
    ),
    "propose_alliance": ToolParityEntry(
        name="propose_alliance",
        module="tools.social_tools",
        category="alliance",
        classification="callable_now",
        rationale="Alliance proposals are internal social governance and use the existing manager.",
    ),
    "vote_alliance": ToolParityEntry(
        name="vote_alliance",
        module="tools.social_tools",
        category="alliance",
        classification="callable_now",
        rationale="Alliance votes are internal governance actions with existing validation.",
    ),
    "leave_alliance": ToolParityEntry(
        name="leave_alliance",
        module="tools.social_tools",
        category="alliance",
        classification="callable_now",
        rationale="Leaving an alliance is internal state managed by the existing alliance manager.",
    ),
    "view_alliances": ToolParityEntry(
        name="view_alliances",
        module="tools.social_tools",
        category="alliance",
        classification="callable_now",
        rationale="Alliance listing is a read-only internal governance lookup.",
    ),
    "manage_task": ToolParityEntry(
        name="manage_task",
        module="tools.task_management",
        category="task",
        classification="callable_now",
        rationale="The shared task board remains useful until the Minecraft blackboard is expanded.",
        linked_issue="#712",
    ),
    "generate_tilemap": ToolParityEntry(
        name="generate_tilemap",
        module="tools.tilemap_gen",
        category="tilemap",
        classification="retired",
        rationale="Phaser tilemap generation is superseded by Minecraft build planning and removal work.",
        linked_issue="#619",
        minecraft_replacement="Minecraft build macros and planner scheduling.",
    ),
    "web_search": ToolParityEntry(
        name="web_search",
        module="tools.web_tools",
        category="web",
        classification="callable_now",
        rationale="Search remains a typed backend tool with rate limiting and cost tracking.",
    ),
    "fetch_url": ToolParityEntry(
        name="fetch_url",
        module="tools.web_tools",
        category="web",
        classification="callable_now",
        rationale="URL fetch remains a typed backend tool with SSRF checks and cost tracking.",
    ),
    "get_world_state": ToolParityEntry(
        name="get_world_state",
        module="tools.world_state",
        category="world_state",
        classification="replaced_by_minecraft",
        rationale="The old Redis world snapshot is superseded by Minecraft perception and shared scene state.",
        linked_issue="#712",
        minecraft_replacement="Minecraft perception snapshot plus shared world/task blackboard.",
    ),
    "propose_build": ToolParityEntry(
        name="propose_build",
        module="tools.build_tools",
        category="world_state",
        classification="callable_now",
        rationale=(
            "Structured BuildIntent submission is the first-class signal for "
            "building; Director V2 routes it to the build macro scheduler."
        ),
        linked_issue="#855",
    ),
    "propose_new_building": ToolParityEntry(
        name="propose_new_building",
        module="tools.build_tools",
        category="world_state",
        classification="callable_now",
        rationale=(
            "Dream-up build proposal: agents describe a brand-new building "
            "structurally; the refinement loop generates an image, "
            "decomposes it, builds it, and iterates against a vision "
            "comparison until the screenshot matches the source image."
        ),
        linked_issue="#861",
    ),
    "claim_ownership": ToolParityEntry(
        name="claim_ownership",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "First-claim-wins ownership ledger is internal civilization "
            "state; Director V2 can route claims through the same backend "
            "ledger without external publication."
        ),
        linked_issue="#891",
    ),
    "release_ownership": ToolParityEntry(
        name="release_ownership",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Releases mutate the same internal ownership ledger and never "
            "touch external systems."
        ),
        linked_issue="#891",
    ),
    "get_ownership": ToolParityEntry(
        name="get_ownership",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale="Read-only ownership lookup for prompt context.",
        linked_issue="#891",
    ),
    "list_my_claims": ToolParityEntry(
        name="list_my_claims",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale="Read-only introspection over the caller's own claims.",
        linked_issue="#891",
    ),
    "propose_trade": ToolParityEntry(
        name="propose_trade",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Pairwise trade proposal: writes a pending offer to the internal "
            "trade ledger and emits a decision-log event. Never publishes "
            "externally."
        ),
        linked_issue="#892",
    ),
    "accept_trade": ToolParityEntry(
        name="accept_trade",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Recipient acceptance atomically swaps two inventories and "
            "(when included) transfers container ownership through the "
            "shared ownership ledger."
        ),
        linked_issue="#892",
    ),
    "reject_trade": ToolParityEntry(
        name="reject_trade",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Recipient rejection records the reason on the offer; no "
            "external publication."
        ),
        linked_issue="#892",
    ),
    "list_pending_trades": ToolParityEntry(
        name="list_pending_trades",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale="Read-only introspection over offers awaiting this agent's reply.",
        linked_issue="#892",
    ),
    "steal": ToolParityEntry(
        name="steal",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Attempt to take items from another agent's container. The "
            "theft ledger rolls a deterministic detection check and, on "
            "detection, emits relationship-delta consequences for the "
            "victim and any in-range witnesses. Never publishes externally."
        ),
        linked_issue="#893",
    ),
    "report_theft": ToolParityEntry(
        name="report_theft",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Witness-driven promotion of a prior undetected theft attempt "
            "to detected; fires the same consequence path as a detected "
            "attempt at roll time."
        ),
        linked_issue="#893",
    ),
    "propose_treaty": ToolParityEntry(
        name="propose_treaty",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Open a treaty between the proposer's faction and another. "
            "The diplomacy ledger persists per sim; no external publish."
        ),
        linked_issue="#894",
    ),
    "sign_treaty": ToolParityEntry(
        name="sign_treaty",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Counterparty member activates a proposed treaty; pure local "
            "ledger mutation with an audit row."
        ),
        linked_issue="#894",
    ),
    "break_treaty": ToolParityEntry(
        name="break_treaty",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Withdraw from an active treaty; emits relationship-delta "
            "trust hits for every other party's members."
        ),
        linked_issue="#894",
    ),
    "defect_faction": ToolParityEntry(
        name="defect_faction",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale=(
            "Move an agent between scenario factions in the diplomacy "
            "ledger and emit the audit row."
        ),
        linked_issue="#894",
    ),
    "list_active_treaties": ToolParityEntry(
        name="list_active_treaties",
        module="tools.civilization",
        category="civilization",
        classification="callable_now",
        rationale="Read-only introspection over the diplomacy ledger.",
        linked_issue="#894",
    ),
}


def classified_names() -> frozenset[str]:
    """Return every tool name with an explicit Director V2 parity decision."""

    return frozenset(TOOL_PARITY)


def is_callable_now(name: str) -> bool:
    """Return true when Director V2 may execute the tool immediately."""

    entry = TOOL_PARITY.get(name)
    return entry is not None and entry.classification == "callable_now"


def is_approval_gated(name: str) -> bool:
    """Return true when Director V2 may only queue or hold the tool for approval."""

    entry = TOOL_PARITY.get(name)
    return entry is not None and entry.classification == "approval_gated"


def iter_tool_parity() -> Iterable[ToolParityEntry]:
    """Iterate parity entries in deterministic tool-name order."""

    for name in sorted(TOOL_PARITY):
        yield TOOL_PARITY[name]
