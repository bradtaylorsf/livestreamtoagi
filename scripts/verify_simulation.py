#!/usr/bin/env python3
"""Comprehensive post-simulation verification.

Checks EVERY subsystem — not just tool presence, but actual DB state,
artifact correctness, relationship updates, reflection outputs, dream
effects, economy transactions, cost accuracy, and error logs.

Usage:
    python scripts/verify_simulation.py --name "tool-coverage"
    python scripts/verify_simulation.py --simulation-id <uuid>

Exits with code 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# All tools that should be exercised (must match tool_coverage.yaml phases)
ALL_TOOLS = sorted([
    "send_message", "get_world_state", "get_audience_status",
    "send_chat_message", "create_poll", "get_poll_results",
    "recall_memory", "retrieve_transcript", "update_core_memory",
    "execute_code", "generate_tilemap",
    "web_search", "fetch_url", "draft_social_post", "draft_email",
    "get_revenue_status",
    "view_account", "transfer_budget",
    "propose_alliance", "vote_alliance", "view_alliances", "leave_alliance",
    "manage_task",
    "propose_character", "vote_character",
    "check_post_performance", "check_email_responses",
    "dispatch_alpha", "propose_self_modification", "view_evolution_log",
])

CONVERSATION_AGENTS = {"aurora", "fork", "grok", "pixel", "rex", "sentinel", "vera"}
LOCAL_PROVIDERS = {"lmstudio", "openai-compatible"}
STATE_DEFAULTS = {
    "energy": 0.7,
    "satisfaction": 0.5,
    "boredom": 0.2,
    "frustration": 0.1,
    "social_need": 0.5,
    "creative_need": 0.3,
    "recognition_need": 0.3,
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, details: str, severity: str = "error") -> None:
        self.checks.append(CheckResult(name, passed, details, severity))

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    def print_report(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"{'SIMULATION VERIFICATION REPORT':^70}")
        print(f"{'=' * 70}\n")

        for c in self.checks:
            marker = "PASS" if c.passed else ("WARN" if c.severity == "warning" else "FAIL")
            print(f"  [{marker}] {c.name}")
            if not c.passed or c.details:
                for line in c.details.split("\n"):
                    if line.strip():
                        print(f"         {line}")

        errors = sum(1 for c in self.checks if not c.passed and c.severity == "error")
        warnings = sum(1 for c in self.checks if not c.passed and c.severity == "warning")
        passed = sum(1 for c in self.checks if c.passed)

        print(f"\n{'=' * 70}")
        print(f"  {passed} passed, {errors} failed, {warnings} warnings")
        if errors == 0:
            print("  RESULT: SIMULATION VERIFIED")
        else:
            print("  RESULT: VERIFICATION FAILED")
        print(f"{'=' * 70}\n")


async def verify(args: argparse.Namespace) -> bool:
    """Run all verification checks."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.simulation_repo import SimulationRepo

    svc = await bootstrap_services()
    sim_repo = SimulationRepo(svc.db)
    report = VerificationReport()

    # Resolve simulation ID
    simulation_id = None
    if args.simulation_id:
        import uuid
        simulation_id = uuid.UUID(args.simulation_id)
    elif args.name:
        sims = await sim_repo.list(limit=100)
        for s in sims:
            if s.name == args.name:
                simulation_id = s.id
                break

    if simulation_id is None:
        print(f"ERROR: No simulation found with name '{args.name}'")
        await shutdown_services(svc)
        return False

    sim = await sim_repo.get(simulation_id)
    if sim is None:
        print(f"ERROR: Simulation {simulation_id} not found")
        await shutdown_services(svc)
        return False

    print(f"Verifying simulation: {sim.name} ({simulation_id})")
    print(f"Status: {sim.status}")
    profile = args.profile
    llm_provider = _infer_llm_provider(sim.config, sim.model_versions)
    is_local = llm_provider in LOCAL_PROVIDERS
    print(f"Profile: {profile}")
    print(f"LLM provider: {llm_provider}")

    # ── 1. Simulation completed successfully ────────────────────
    report.add(
        "Simulation status",
        sim.status == "completed",
        f"Expected 'completed', got '{sim.status}'",
    )

    # ── 2. No runtime errors in error_log ──────────────────────
    error_log = sim.error_log
    runtime_errors = []
    if isinstance(error_log, dict):
        runtime_errors = error_log.get("runtime_errors", [])
    elif isinstance(error_log, list):
        runtime_errors = error_log

    report.add(
        "No runtime errors",
        len(runtime_errors) == 0,
        f"{len(runtime_errors)} runtime errors found:\n" + "\n".join(
            "  - "
            f"[{e.get('error_type', '?')}] {e.get('source', '?')}: "
            f"{str(e.get('detail', ''))[:100]}"
            for e in runtime_errors[:10]
        ) if runtime_errors else "Clean",
    )

    # ── 3. Model provenance ────────────────────────────────────
    model_values = [
        value
        for agent_versions in (sim.model_versions or {}).values()
        for value in agent_versions.values()
    ]
    if is_local:
        non_local_models = [
            value for value in model_values
            if not any(str(value).startswith(f"{p}:") for p in LOCAL_PROVIDERS)
        ]
        report.add(
            "Local model provenance",
            len(model_values) > 0 and len(non_local_models) == 0,
            "All model versions point at the local provider"
            if model_values and not non_local_models else
            f"Non-local model entries: {non_local_models[:5]}",
        )
    else:
        report.add(
            "Model provenance recorded",
            len(model_values) > 0,
            f"{len(model_values)} model version entries",
            severity="warning",
        )

    # ── 4. Tool coverage — all tools exercised for comprehensive profiles ─
    artifact_rows = await svc.db.fetch(
        """SELECT tool_name, agent_id, status, tool_output
           FROM artifacts
           WHERE simulation_id = $1
           ORDER BY tool_name""",
        simulation_id,
    )

    found_tools: dict[str, list[dict]] = {}
    for row in artifact_rows:
        tool = row["tool_name"]
        if tool not in found_tools:
            found_tools[tool] = []
        found_tools[tool].append({
            "agent": row["agent_id"],
            "status": row["status"],
            "output": row["tool_output"],
        })

    if profile in {"comprehensive", "tool-coverage"}:
        missing_tools = [t for t in ALL_TOOLS if t not in found_tools]
        report.add(
            f"Tool coverage ({len(ALL_TOOLS) - len(missing_tools)}/{len(ALL_TOOLS)})",
            len(missing_tools) == 0,
            f"Missing: {', '.join(missing_tools)}" if missing_tools else "All tools exercised",
        )
    else:
        report.add(
            f"Tool activity ({len(found_tools)} distinct tools)",
            len(found_tools) >= 1,
            f"Tools observed: {', '.join(sorted(found_tools)[:8])}"
            if found_tools else "No tools fired",
            severity="warning",
        )

    # ── 5. Tool execution status — all should be "executed" ────
    failed_tools = []
    for tool_name, entries in found_tools.items():
        for entry in entries:
            if entry["status"] != "executed":
                failed_tools.append(f"{tool_name} ({entry['agent']}): status={entry['status']}")

    report.add(
        "Tool execution status",
        len(failed_tools) == 0,
        f"{len(failed_tools)} failed:\n" + "\n".join(f"  - {t}" for t in failed_tools[:10])
        if failed_tools else "All tools executed successfully",
    )

    # ── 6. Tool outputs — check for error payloads ─────────────
    error_outputs = []
    for tool_name, entries in found_tools.items():
        for entry in entries:
            output = entry.get("output")
            if isinstance(output, dict) and "error" in output:
                error_outputs.append(f"{tool_name} ({entry['agent']}): {str(output['error'])[:80]}")

    report.add(
        "Tool output correctness",
        len(error_outputs) == 0,
        f"{len(error_outputs)} tools returned errors:\n"
        + "\n".join(f"  - {e}" for e in error_outputs[:10])
        if error_outputs else "No error payloads in tool outputs",
    )

    # ── 7. Conversations happened ──────────────────────────────
    conv_rows = await svc.db.fetch(
        """SELECT id, trigger_type, turn_count, participating_agents
           FROM conversations
           WHERE simulation_id = $1""",
        simulation_id,
    )

    min_conversations = 2 if profile == "local-smoke" else 5
    report.add(
        f"Conversations created ({len(conv_rows)})",
        len(conv_rows) >= min_conversations,
        f"Expected >= {min_conversations}, got {len(conv_rows)}",
    )

    zero_turn_convs = [r for r in conv_rows if (r["turn_count"] or 0) == 0]
    report.add(
        "Conversations with turns",
        len(zero_turn_convs) <= 2,  # Allow a couple of empty convs
        f"{len(zero_turn_convs)} conversations had 0 turns",
        severity="warning" if len(zero_turn_convs) <= 5 else "error",
    )

    # ── 8. Cost / LLM-call tracking ────────────────────────────
    cost_rows = await svc.db.fetch(
        """SELECT cost_type, SUM(amount) as total, COUNT(*) as count
           FROM cost_events
           WHERE simulation_id = $1
           GROUP BY cost_type""",
        simulation_id,
    )

    total_cost_from_events = sum(Decimal(str(r["total"])) for r in cost_rows)
    llm_call_count = sum(r["count"] for r in cost_rows if r["cost_type"] == "llm_call")
    report.add(
        f"LLM calls tracked ({llm_call_count}, ${total_cost_from_events:.4f})",
        llm_call_count > 0 and (is_local or total_cost_from_events > 0),
        "No LLM call events found — LLM calls not tracked!"
        if llm_call_count == 0 else
        f"Cost types: {', '.join(r['cost_type'] + '=' + str(r['count']) for r in cost_rows)}",
    )

    if is_local:
        local_call_count = await svc.db.fetchval(
            """SELECT COUNT(*) FROM cost_events
               WHERE simulation_id = $1
                 AND cost_type = 'llm_call'
                 AND details->>'provider' = ANY($2::text[])""",
            simulation_id,
            list(LOCAL_PROVIDERS),
        )
        report.add(
            f"Local provider LLM calls ({local_call_count})",
            local_call_count > 0,
            "LLM calls include local provider provenance"
            if local_call_count else "No llm_call rows had local provider details",
        )

    # Check cost reconciliation with simulation record
    if sim.total_cost is not None and total_cost_from_events > 0:
        sim_cost = Decimal(str(sim.total_cost))
        diff = abs(sim_cost - total_cost_from_events)
        report.add(
            "Cost reconciliation",
            diff < Decimal("0.01"),
            f"Sim record: ${sim_cost:.4f}, "
            f"cost_events: ${total_cost_from_events:.4f}, diff: ${diff:.4f}",
            severity="warning",
        )

    # ── 9. Energy model evidence ───────────────────────────────
    energy_rows = await svc.db.fetch(
        """SELECT changes
           FROM energy_change_log
           WHERE simulation_id = $1""",
        simulation_id,
    )
    nonzero_energy = 0
    for row in energy_rows:
        changes = row["changes"]
        if isinstance(changes, str):
            import json as _json
            changes = _json.loads(changes)
        if abs(float(changes.get("net", 0))) > 0.0001:
            nonzero_energy += 1
    report.add(
        f"Conversation energy logged ({len(energy_rows)} ticks)",
        len(energy_rows) > 0 and nonzero_energy > 0,
        f"{nonzero_energy} ticks changed energy" if energy_rows else "No energy log rows",
    )

    # ── 10. Relationships created ──────────────────────────────
    rel_rows = await svc.db.fetch(
        """SELECT agent_id, target_agent_id, sentiment_score, interaction_count
           FROM agent_relationships
           WHERE simulation_id = $1""",
        simulation_id,
    )

    report.add(
        f"Relationships tracked ({len(rel_rows)} pairs)",
        len(rel_rows) >= 2,
        "No relationships were created — RelationshipTracker may not be firing"
        if len(rel_rows) == 0 else
        f"Pairs: {', '.join(r['agent_id'] + '->' + r['target_agent_id'] for r in rel_rows[:5])}...",
    )

    # ── 11. Journal entries from reflection ────────────────────
    journal_rows = await svc.db.fetch(
        """SELECT agent_id, reflection_type, image_url
           FROM journal_entries
           WHERE simulation_id = $1""",
        simulation_id,
    )

    six_hour = [j for j in journal_rows if j["reflection_type"] == "6hour"]
    dreams = [j for j in journal_rows if j["reflection_type"] == "dream"]

    report.add(
        f"Journal entries from reflection ({len(six_hour)} 6-hour)",
        len(six_hour) >= 1,
        f"Expected at least 1 agent to produce a 6-hour journal, got {len(six_hour)}",
    )

    report.add(
        f"Dream journal entries ({len(dreams)})",
        len(dreams) >= 1,
        f"Expected at least 1 agent to dream, got {len(dreams)}",
    )

    # Check image generation
    images = [j for j in journal_rows if j.get("image_url")]
    report.add(
        f"Journal images generated ({len(images)})",
        len(images) >= 1,
        "No journal images were generated — GOOGLE_IMAGEN_API_KEY may not be set or API failed",
        severity="warning",
    )

    # ── 12. Core memory was updated ────────────────────────────
    core_mem_rows = await svc.db.fetch(
        """SELECT agent_id, LENGTH(content) as content_len
           FROM core_memory
           WHERE simulation_id = $1""",
        simulation_id,
    )

    report.add(
        f"Core memories initialized ({len(core_mem_rows)} agents)",
        len(core_mem_rows) >= len(CONVERSATION_AGENTS),
        f"Expected {len(CONVERSATION_AGENTS)} agents, got {len(core_mem_rows)}",
    )

    # ── 13. Recall memories created ────────────────────────────
    recall_count = await svc.db.fetchval(
        "SELECT COUNT(*) FROM recall_memory WHERE simulation_id = $1",
        simulation_id,
    )

    report.add(
        f"Recall memories created ({recall_count})",
        recall_count >= 1,
        "No recall memories — compaction/archival may not be running"
        if recall_count == 0 else f"{recall_count} recall memories stored",
    )

    # ── 14. Agent goals seeded and tracked ─────────────────────
    goal_rows = await svc.db.fetch(
        """SELECT agent_id, COUNT(*) as count
           FROM agent_goals
           WHERE simulation_id = $1
           GROUP BY agent_id""",
        simulation_id,
    )

    total_goals = sum(r["count"] for r in goal_rows)
    report.add(
        f"Agent goals tracked ({total_goals} across {len(goal_rows)} agents)",
        total_goals >= 1,
        "No goals were created — seed_goals may not have fired",
    )

    dream_goal_count = await svc.db.fetchval(
        """SELECT COUNT(*) FROM agent_goals
           WHERE simulation_id = $1 AND source = 'dream'""",
        simulation_id,
    )
    report.add(
        f"Dream-generated goals ({dream_goal_count})",
        profile != "local-smoke" or dream_goal_count >= 1,
        "Dreams produced at least one goal"
        if dream_goal_count else "No dream goals were persisted",
        severity="warning" if profile != "local-smoke" else "error",
    )

    # ── 15. Economy accounts exist ─────────────────────────────
    account_rows = await svc.db.fetch(
        """SELECT agent_id, balance
           FROM agent_accounts
           WHERE simulation_id = $1""",
        simulation_id,
    )

    expected_econ_agents = CONVERSATION_AGENTS - {"management", "alpha"}
    report.add(
        f"Economy accounts ({len(account_rows)} agents)",
        len(account_rows) >= len(expected_econ_agents) - 2,  # allow some tolerance
        f"Expected ~{len(expected_econ_agents)}, got {len(account_rows)}",
    )

    # ── 16. Agent internal state was tracked ───────────────────
    state_rows = await svc.db.fetch(
        """SELECT agent_id, energy, satisfaction, boredom, frustration,
                  social_need, creative_need, recognition_need, mood
           FROM agent_internal_state
           WHERE simulation_id = $1""",
        simulation_id,
    )

    report.add(
        f"Agent internal state snapshots ({len(state_rows)})",
        len(state_rows) >= 1,
        "No agent state snapshots — AgentStateManager may not be persisting",
        severity="warning",
    )
    changed_states = 0
    moods = set()
    for row in state_rows:
        state = dict(row)
        moods.add(state["mood"])
        for key, default in STATE_DEFAULTS.items():
            if key in state and abs(float(state[key]) - default) > 0.0001:
                changed_states += 1
                break
    report.add(
        f"Agent emotional state changed ({changed_states} agents)",
        changed_states >= 1,
        f"Moods observed: {', '.join(sorted(moods))}" if moods else "No moods observed",
    )

    # ── 17. Management shadow logs ─────────────────────────────
    mgmt_rows = await svc.db.fetch(
        """SELECT COUNT(*) as count FROM management_shadow_log
           WHERE simulation_id = $1""",
        simulation_id,
    )

    mgmt_count = mgmt_rows[0]["count"] if mgmt_rows else 0
    report.add(
        f"Management shadow logs ({mgmt_count})",
        mgmt_count >= 1,
        "No management shadow logs — content filter may not be running",
        severity="warning",
    )

    # ── 18. Transcripts stored ─────────────────────────────────
    transcript_count = await svc.db.fetchval(
        """SELECT COUNT(*) FROM transcripts t
           JOIN conversations c ON t.conversation_id = c.id
           WHERE c.simulation_id = $1""",
        simulation_id,
    )

    report.add(
        f"Transcripts archived ({transcript_count})",
        transcript_count >= 1,
        "No transcripts stored — archival memory not running",
    )

    # ── 19. Cost diagnostics from LLM client ──────────────────
    diag = svc.llm_client.diagnostics()
    lost = diag.get("lost_cost_events", 0)
    report.add(
        "Cost event loss rate",
        lost == 0,
        f"{lost} cost events were lost during the simulation"
        if lost > 0 else "No cost events lost",
    )

    # ── 20. Per-agent participation ────────────────────────────
    agent_turns = await svc.db.fetch(
        """SELECT ce.agent_id, COUNT(*) as turns
           FROM cost_events ce
           WHERE ce.simulation_id = $1 AND ce.agent_id IS NOT NULL
           GROUP BY ce.agent_id""",
        simulation_id,
    )

    participating = {r["agent_id"] for r in agent_turns}
    expected_participants = CONVERSATION_AGENTS
    if profile == "local-smoke":
        import json as _json
        expected_participants = set()
        for row in conv_rows:
            participants = row["participating_agents"] or []
            if isinstance(participants, str):
                participants = _json.loads(participants)
            expected_participants.update(participants)
        expected_participants -= {"management", "alpha"}
        if not expected_participants:
            expected_participants = CONVERSATION_AGENTS
    missing_agents = expected_participants - participating - {"management", "alpha", "system"}
    report.add(
        f"Agent participation ({len(participating)} agents active)",
        len(missing_agents) == 0,
        f"Missing agents: {', '.join(missing_agents)}"
        if missing_agents else "All conversation agents participated",
    )

    await shutdown_services(svc)

    report.print_report()
    return report.passed


def _infer_llm_provider(config: dict | None, model_versions: dict | None) -> str:
    """Infer the provider used by a simulation record."""
    if isinstance(config, dict) and config.get("llm_provider"):
        return str(config["llm_provider"])
    if isinstance(model_versions, dict):
        for agent_versions in model_versions.values():
            if isinstance(agent_versions, dict):
                for value in agent_versions.values():
                    text = str(value)
                    if ":" in text:
                        return text.split(":", 1)[0]
    return "openrouter"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Comprehensive simulation verification"
    )
    parser.add_argument("--name", type=str, help="Simulation name")
    parser.add_argument("--simulation-id", type=str, help="Simulation UUID")
    parser.add_argument(
        "--profile",
        choices=["comprehensive", "tool-coverage", "local-smoke"],
        default="comprehensive",
        help="Verification profile (default: comprehensive)",
    )

    args = parser.parse_args()
    if not args.name and not args.simulation_id:
        parser.error("Either --name or --simulation-id must be provided")

    success = asyncio.run(verify(args))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
