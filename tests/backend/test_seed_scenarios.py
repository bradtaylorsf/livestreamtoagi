"""Tests for seed scenario YAML files.

Validates structure, tool coverage, and consistency of all scenario files
in the scenarios/ directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "scenarios"

# All 21 tools that must be exercisable
ALL_TOOLS = {
    "send_message",
    "read_core_memory",
    "update_core_memory",
    "recall_memory",
    "retrieve_transcript",
    "execute_code",
    "generate_tilemap",
    "web_search",
    "fetch_url",
    "draft_social_post",
    "draft_email",
    "create_poll",
    "get_poll_results",
    "send_chat_message",
    "get_world_state",
    "get_audience_status",
    "dispatch_alpha",
    "get_revenue_status",
    "propose_self_modification",
    "view_evolution_log",
}

# Valid phase types from the orchestrator
VALID_PHASE_TYPES = {
    "scheduled",
    "organic",
    "challenge",
    "tool_exercise",
    "reflection",
    "audience_sim",
}

# Valid agent IDs
VALID_AGENTS = {
    "vera",
    "rex",
    "aurora",
    "pixel",
    "fork",
    "sentinel",
    "grok",
    "alpha",
    "overseer",
}

# Tool-to-agent authorization constraints
TOOL_AGENT_RESTRICTIONS: dict[str, set[str]] = {
    "send_chat_message": {"pixel", "sentinel", "vera"},
    "create_poll": {"vera", "pixel"},
    "execute_code": {"rex", "fork", "sentinel"},
    "generate_tilemap": {"rex", "fork"},
    "web_search": {"pixel", "grok", "aurora", "vera"},
    "get_revenue_status": {"sentinel", "vera"},
}

SCENARIO_FILES = [
    "full_day.yaml",
    "quick_smoke.yaml",
    "tool_coverage.yaml",
    "drama.yaml",
]


def load_scenario(filename: str) -> dict:
    """Load and parse a scenario YAML file."""
    path = SCENARIOS_DIR / filename
    assert path.exists(), f"Scenario file not found: {path}"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture(params=SCENARIO_FILES)
def scenario(request: pytest.FixtureRequest) -> tuple[str, dict]:
    """Parametrized fixture that yields (filename, parsed_data) for each scenario."""
    return request.param, load_scenario(request.param)


class TestScenarioStructure:
    """Validate YAML structure of all scenario files."""

    def test_scenario_files_exist(self) -> None:
        """All required scenario files must exist."""
        for filename in SCENARIO_FILES:
            path = SCENARIOS_DIR / filename
            assert path.exists(), f"Missing scenario file: {filename}"

    def test_has_phases(self, scenario: tuple[str, dict]) -> None:
        """Every scenario must have a non-empty phases list."""
        filename, data = scenario
        assert "phases" in data, f"{filename}: missing 'phases' key"
        assert len(data["phases"]) > 0, f"{filename}: phases list is empty"

    def test_phase_has_required_fields(self, scenario: tuple[str, dict]) -> None:
        """Each phase must have name and type."""
        filename, data = scenario
        for i, phase in enumerate(data["phases"]):
            assert "name" in phase, f"{filename}: phase {i} missing 'name'"
            assert "type" in phase, f"{filename}: phase {i} missing 'type'"

    def test_phase_types_valid(self, scenario: tuple[str, dict]) -> None:
        """All phase types must be recognized by the orchestrator."""
        filename, data = scenario
        for phase in data["phases"]:
            assert phase["type"] in VALID_PHASE_TYPES, (
                f"{filename}: phase '{phase['name']}' has invalid type "
                f"'{phase['type']}'"
            )

    def test_phase_names_unique(self, scenario: tuple[str, dict]) -> None:
        """Phase names must be unique within a scenario."""
        filename, data = scenario
        names = [p["name"] for p in data["phases"]]
        dupes = [n for n in names if names.count(n) > 1]
        assert not dupes, f"{filename}: duplicate phase names: {set(dupes)}"


class TestPhaseTypeConfig:
    """Validate type-specific configuration for each phase."""

    def test_scheduled_phases_have_trigger(self, scenario: tuple[str, dict]) -> None:
        """Scheduled phases must have a trigger."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "scheduled":
                assert "trigger" in phase or "required_agents" in phase, (
                    f"{filename}: scheduled phase '{phase['name']}' needs "
                    f"trigger or required_agents"
                )

    def test_tool_exercise_phases_have_tool(self, scenario: tuple[str, dict]) -> None:
        """Tool exercise phases must specify agent and tool."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "tool_exercise":
                assert "agent" in phase, (
                    f"{filename}: tool_exercise '{phase['name']}' missing 'agent'"
                )
                assert "tool" in phase, (
                    f"{filename}: tool_exercise '{phase['name']}' missing 'tool'"
                )

    def test_challenge_phases_have_challenge(self, scenario: tuple[str, dict]) -> None:
        """Challenge phases must have a challenge object with required fields."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "challenge":
                assert "challenge" in phase, (
                    f"{filename}: challenge phase '{phase['name']}' missing "
                    f"'challenge' object"
                )
                ch = phase["challenge"]
                for field in ("title", "description", "assigned_to", "language"):
                    assert field in ch, (
                        f"{filename}: challenge '{phase['name']}' missing "
                        f"field '{field}'"
                    )

    def test_audience_sim_phases_have_messages(
        self, scenario: tuple[str, dict]
    ) -> None:
        """Audience sim phases must have a messages list."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "audience_sim":
                assert "messages" in phase, (
                    f"{filename}: audience_sim '{phase['name']}' missing 'messages'"
                )
                assert len(phase["messages"]) > 0, (
                    f"{filename}: audience_sim '{phase['name']}' has empty messages"
                )

    def test_reflection_phases_have_agents(self, scenario: tuple[str, dict]) -> None:
        """Reflection phases must specify agents."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "reflection":
                assert "agents" in phase, (
                    f"{filename}: reflection '{phase['name']}' missing 'agents'"
                )

    def test_organic_phases_have_count(self, scenario: tuple[str, dict]) -> None:
        """Organic phases should have a count."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] == "organic":
                assert "count" in phase, (
                    f"{filename}: organic '{phase['name']}' missing 'count'"
                )


class TestAgentAuthorization:
    """Validate that tools are assigned to authorized agents."""

    def test_tool_exercise_agent_authorized(
        self, scenario: tuple[str, dict]
    ) -> None:
        """Tool exercise phases must use authorized agents."""
        filename, data = scenario
        for phase in data["phases"]:
            if phase["type"] != "tool_exercise":
                continue
            tool = phase.get("tool", "")
            agent = phase.get("agent", "")
            if tool in TOOL_AGENT_RESTRICTIONS:
                allowed = TOOL_AGENT_RESTRICTIONS[tool]
                assert agent in allowed, (
                    f"{filename}: phase '{phase['name']}' assigns '{tool}' "
                    f"to '{agent}', but only {allowed} are authorized"
                )

    def test_challenge_agents_can_execute_code(
        self, scenario: tuple[str, dict]
    ) -> None:
        """Challenge phases must assign to agents who can execute code."""
        filename, data = scenario
        code_agents = TOOL_AGENT_RESTRICTIONS["execute_code"]
        for phase in data["phases"]:
            if phase["type"] != "challenge":
                continue
            assigned = phase.get("challenge", {}).get("assigned_to", "")
            assert assigned in code_agents, (
                f"{filename}: challenge '{phase['name']}' assigns to "
                f"'{assigned}', but only {code_agents} can execute code"
            )

    def test_all_agents_valid(self, scenario: tuple[str, dict]) -> None:
        """All referenced agents must be valid agent IDs."""
        filename, data = scenario
        for phase in data["phases"]:
            # Check agent in tool_exercise
            if "agent" in phase:
                assert phase["agent"] in VALID_AGENTS, (
                    f"{filename}: unknown agent '{phase['agent']}'"
                )
            # Check required_agents
            for agent in phase.get("required_agents", []):
                assert agent in VALID_AGENTS, (
                    f"{filename}: unknown agent '{agent}'"
                )
            # Check challenge assigned_to
            if "challenge" in phase:
                assigned = phase["challenge"].get("assigned_to", "")
                if assigned:
                    assert assigned in VALID_AGENTS, (
                        f"{filename}: unknown agent '{assigned}'"
                    )
            # Check reflection agents
            for agent in phase.get("agents", []):
                assert agent in VALID_AGENTS, (
                    f"{filename}: unknown agent '{agent}'"
                )


class TestToolCoverage:
    """Validate tool coverage guarantees."""

    def _extract_tools(self, data: dict) -> set[str]:
        """Extract all tools exercised in a scenario."""
        tools: set[str] = set()
        for phase in data.get("phases", []):
            ptype = phase.get("type", "")
            if ptype == "tool_exercise":
                tool = phase.get("tool")
                if tool:
                    tools.add(tool)
            elif ptype == "challenge":
                tools.add("execute_code")
            elif ptype == "scheduled":
                tools.add("send_message")
            elif ptype == "audience_sim":
                tools.add("send_message")
            elif ptype == "reflection":
                tools.add("update_core_memory")
            elif ptype == "organic":
                tools.add("send_message")
        return tools

    def test_full_day_covers_all_tools(self) -> None:
        """full_day.yaml must exercise every tool at least once."""
        data = load_scenario("full_day.yaml")
        covered = self._extract_tools(data)
        missing = ALL_TOOLS - covered
        assert not missing, (
            f"full_day.yaml missing tool coverage for: {missing}"
        )

    def test_tool_coverage_covers_all_tools(self) -> None:
        """tool_coverage.yaml must exercise every tool at least once."""
        data = load_scenario("tool_coverage.yaml")
        covered = self._extract_tools(data)
        missing = ALL_TOOLS - covered
        assert not missing, (
            f"tool_coverage.yaml missing tool coverage for: {missing}"
        )

    def test_tool_coverage_has_one_phase_per_tool(self) -> None:
        """tool_coverage.yaml should have at least one phase per tool."""
        data = load_scenario("tool_coverage.yaml")
        tool_phases = [
            p for p in data["phases"] if p["type"] == "tool_exercise"
        ]
        tools_covered = {p["tool"] for p in tool_phases}
        # All tools except send_message (covered by scheduled) and
        # update_core_memory (covered by reflection) and execute_code
        # (can be covered by either tool_exercise or challenge)
        tool_exercise_tools = ALL_TOOLS - {"send_message", "update_core_memory"}
        missing = tool_exercise_tools - tools_covered
        # execute_code might be a challenge instead
        if "execute_code" in missing:
            has_challenge = any(
                p["type"] == "challenge" for p in data["phases"]
            )
            if has_challenge:
                missing.discard("execute_code")
        assert not missing, (
            f"tool_coverage.yaml missing dedicated phase for: {missing}"
        )


class TestQuickSmoke:
    """Validate quick_smoke.yaml specific requirements."""

    def test_has_five_phases(self) -> None:
        """quick_smoke.yaml should have exactly 5 phases."""
        data = load_scenario("quick_smoke.yaml")
        assert len(data["phases"]) == 5, (
            f"quick_smoke.yaml has {len(data['phases'])} phases, expected 5"
        )

    def test_covers_core_tools(self) -> None:
        """quick_smoke.yaml must cover core tools."""
        data = load_scenario("quick_smoke.yaml")
        phase_types = {p["type"] for p in data["phases"]}
        # Must have at least these phase types for basic coverage
        assert "tool_exercise" in phase_types or "challenge" in phase_types
        assert "reflection" in phase_types


class TestDrama:
    """Validate drama.yaml specific requirements."""

    def test_has_conflict_phases(self) -> None:
        """drama.yaml should include conflict/disagreement phases."""
        data = load_scenario("drama.yaml")
        phase_names = [p["name"] for p in data["phases"]]
        # Should have phases that involve conflict
        conflict_keywords = [
            "fight", "argument", "debate", "panic", "chaos",
            "confrontation", "provocation", "controversy",
        ]
        has_conflict = any(
            any(kw in name for kw in conflict_keywords)
            for name in phase_names
        )
        assert has_conflict, (
            "drama.yaml should have phases with conflict-related names"
        )

    def test_has_audience_events(self) -> None:
        """drama.yaml should have audience events."""
        data = load_scenario("drama.yaml")
        assert "audience_events" in data, (
            "drama.yaml missing audience_events"
        )
        assert len(data["audience_events"]) > 0

    def test_grok_is_involved(self) -> None:
        """drama.yaml should heavily feature Grok."""
        data = load_scenario("drama.yaml")
        grok_phases = 0
        for phase in data["phases"]:
            if phase.get("agent") == "grok":
                grok_phases += 1
            if "grok" in phase.get("required_agents", []):
                grok_phases += 1
        assert grok_phases >= 3, (
            f"drama.yaml should feature Grok in at least 3 phases, "
            f"found {grok_phases}"
        )


class TestAudienceEvents:
    """Validate audience event definitions."""

    VALID_EVENT_TYPES = {"chat_message", "poll_response", "donation", "subscription"}

    def test_audience_events_structure(self, scenario: tuple[str, dict]) -> None:
        """Audience events must have required fields."""
        filename, data = scenario
        events = data.get("audience_events", [])
        for i, event in enumerate(events):
            assert "type" in event, (
                f"{filename}: audience event {i} missing 'type'"
            )
            assert event["type"] in self.VALID_EVENT_TYPES, (
                f"{filename}: audience event {i} has invalid type "
                f"'{event['type']}'"
            )
            assert "content" in event, (
                f"{filename}: audience event {i} missing 'content'"
            )
            assert "sender_name" in event, (
                f"{filename}: audience event {i} missing 'sender_name'"
            )


class TestCodingChallenges:
    """Validate coding challenge definitions."""

    def test_full_day_has_coding_challenges(self) -> None:
        """full_day.yaml must include coding challenges."""
        data = load_scenario("full_day.yaml")
        challenges = [
            p for p in data["phases"] if p["type"] == "challenge"
        ]
        assert len(challenges) >= 3, (
            f"full_day.yaml has {len(challenges)} challenges, expected >= 3"
        )

    def test_coding_challenges_summary(self) -> None:
        """full_day.yaml should have a coding_challenges summary section."""
        data = load_scenario("full_day.yaml")
        assert "coding_challenges" in data, (
            "full_day.yaml missing coding_challenges summary"
        )
        for ch in data["coding_challenges"]:
            for field in (
                "title", "description", "language",
                "assigned_agent", "difficulty",
            ):
                assert field in ch, (
                    f"Coding challenge missing field '{field}': {ch.get('title')}"
                )

    def test_challenge_difficulties_valid(self) -> None:
        """Challenge difficulties must be easy, medium, or hard."""
        data = load_scenario("full_day.yaml")
        valid = {"easy", "medium", "hard"}
        for ch in data.get("coding_challenges", []):
            assert ch["difficulty"] in valid, (
                f"Invalid difficulty '{ch['difficulty']}' for "
                f"challenge '{ch['title']}'"
            )
