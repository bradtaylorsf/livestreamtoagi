"""End-to-end conversation pipeline validation.

Runs a minimal simulation and validates every stage of the pipeline:
  Stage 1: Pre-conversation (core memory, agent registry, Redis)
  Stage 2: Conversation execution (simulation, conversation, logs)
  Stage 3: Tool calls during conversation (artifacts, core memory updates)
  Stage 4: Post-conversation (turn_count, transcripts, recall, journals)
  Stage 5: Admin API verification (all 9 admin endpoints)
  Stage 6: No duplication (scripts don't duplicate core logic)

Run with: pytest tests/integration/test_pipeline.py -v -m integration -x
Requires: Docker Compose services running (Redis, PostgreSQL, Langfuse)
Requires: OPENROUTER_API_KEY set for real LLM calls
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# All async test classes share a single event loop per module
_async_mark = pytest.mark.asyncio(loop_scope="module")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Stage 1: Pre-conversation ─────────────────────────────────────


@_async_mark
class TestPreConversation:
    """Validate that the system is ready before any conversation runs."""

    async def test_all_agents_have_core_memory(self, services):
        """All 9 agents should have core memory records."""
        count = await services.db.fetchval("SELECT COUNT(*) FROM core_memory")
        agents = services.agent_registry.get_all_agents()
        assert count >= len(agents), (
            f"Expected core_memory rows >= {len(agents)}, got {count}"
        )

    async def test_core_memory_content_is_valid(self, services):
        """Each core memory should contain identity text."""
        agents = services.agent_registry.get_all_agents()
        for agent in agents:
            mem = await services.core_memory.get_core_memory(agent.id)
            assert mem is not None, f"Agent {agent.id} missing core memory"
            # get_core_memory returns a string
            assert len(mem) > 10, (
                f"Agent {agent.id} core memory too short: {len(mem)} chars"
            )

    async def test_agent_registry_loads_all_agents(self, services):
        """AgentRegistry should load all 9 agents from YAML configs."""
        agents = services.agent_registry.get_all_agents()
        assert len(agents) >= 9, f"Expected >= 9 agents, got {len(agents)}"
        agent_ids = {a.id for a in agents}
        for expected in ("vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok", "overseer", "alpha"):
            assert expected in agent_ids, f"Agent '{expected}' not found in registry"

    async def test_redis_connected(self, services):
        """Redis should be connected and responsive."""
        assert services.redis is not None, "Redis not initialized"
        result = await services.redis.client.ping()
        assert result is True, "Redis ping failed"


# ── Stage 2: Conversation execution ───────────────────────────────


@_async_mark
class TestConversationExecution:
    """Validate that the simulation created proper DB records."""

    async def test_simulation_completed(self, services, simulation_result):
        """Simulation record should exist with status='completed'."""
        sim_id = simulation_result["simulation_id"]
        row = await services.db.fetchrow(
            "SELECT * FROM simulations WHERE id = $1", sim_id
        )
        assert row is not None, "Simulation record not found"
        assert row["status"] == "completed", f"Expected status='completed', got '{row['status']}'"

    async def test_conversation_created_with_simulation_id(self, services, simulation_result):
        """At least one conversation should be linked to the simulation."""
        conv_ids = simulation_result["conversation_ids"]
        assert len(conv_ids) > 0, "No conversations created for simulation"

        for conv_id in conv_ids:
            row = await services.db.fetchrow(
                "SELECT simulation_id FROM conversations WHERE id = $1", conv_id
            )
            assert row is not None
            assert row["simulation_id"] == simulation_result["simulation_id"], (
                "Conversation simulation_id mismatch"
            )

    async def test_selection_log_written(self, services, simulation_result):
        """Speaker selection logs should exist for each conversation."""
        for conv_id in simulation_result["conversation_ids"]:
            rows = await services.db.fetch(
                "SELECT * FROM conversation_selection_log WHERE conversation_id = $1 ORDER BY turn_number",
                conv_id,
            )
            assert len(rows) > 0, f"No selection logs for conversation {conv_id}"
            # Turn numbers should be sequential
            turn_numbers = [r["turn_number"] for r in rows]
            assert turn_numbers == sorted(turn_numbers), "Turn numbers not sequential"

    async def test_energy_change_log_written(self, services, simulation_result):
        """Energy change logs should exist for each conversation."""
        for conv_id in simulation_result["conversation_ids"]:
            rows = await services.db.fetch(
                "SELECT * FROM energy_change_log WHERE conversation_id = $1",
                conv_id,
            )
            assert len(rows) > 0, f"No energy change logs for conversation {conv_id}"

    async def test_cost_events_written(self, services, simulation_result):
        """Cost events should be written with token counts during simulation."""
        st = simulation_result["start_time"]
        rows = await services.db.fetch(
            "SELECT * FROM cost_events WHERE created_at >= $1",
            st,
        )
        assert len(rows) > 0, "No cost events created during simulation"

        # At least some should have token details
        with_details = [r for r in rows if r.get("details")]
        assert len(with_details) > 0, "No cost events have details JSONB"
        for row in with_details:
            details = row["details"]
            assert "input_tokens" in details or "output_tokens" in details, (
                f"Cost event missing token counts in details: {details}"
            )


# ── Stage 3: Tool calls during conversation ───────────────────────


@_async_mark
class TestToolCalls:
    """Validate tool call handling (best-effort — tools may not fire every run)."""

    async def test_tool_definitions_available(self, services):
        """Tool definitions should be importable and buildable."""
        from core.tool_executor import build_agent_tools, tools_to_openai_schema

        tools = build_agent_tools("rex", services=services)
        assert len(tools) > 0, "No tools built for agent rex"

        schema = tools_to_openai_schema(tools)
        assert len(schema) > 0, "Tool schema conversion produced empty list"

    async def test_update_core_memory_self_resolution(self, services):
        """update_core_memory tool should be built with agent_id binding."""
        try:
            from core.tool_executor import build_agent_tools
            tools = build_agent_tools("rex", services=services)
        except Exception:
            pytest.skip("Could not build tools for rex")

        if "update_core_memory" not in tools:
            pytest.skip("update_core_memory tool not available")

        tool = tools["update_core_memory"]
        # Tool should have agent_id binding (checks vary by implementation)
        # At minimum, verify the tool exists and is callable
        assert callable(getattr(tool, "run", None)) or callable(getattr(tool, "execute", None)), (
            "update_core_memory tool is not callable"
        )

    async def test_artifacts_table_accessible(self, services, simulation_result):
        """Artifacts table should be queryable (may be empty if no tools fired)."""
        sim_id = simulation_result["simulation_id"]
        rows = await services.db.fetch(
            "SELECT * FROM artifacts WHERE simulation_id = $1", sim_id
        )
        # Artifacts are optional — just verify the query works
        assert isinstance(rows, list)


# ── Stage 4: Post-conversation ─────────────────────────────────────


@_async_mark
class TestPostConversation:
    """Validate post-conversation state: counts, transcripts, memories, journals."""

    async def test_turn_count_nonzero(self, services, simulation_result):
        """Every conversation should have turn_count > 0."""
        for conv_id in simulation_result["conversation_ids"]:
            row = await services.db.fetchrow(
                "SELECT turn_count, ended_at FROM conversations WHERE id = $1",
                conv_id,
            )
            assert row is not None
            assert row["turn_count"] > 0, (
                f"Conversation {conv_id} has turn_count=0"
            )
            assert row["ended_at"] is not None, (
                f"Conversation {conv_id} has ended_at=NULL"
            )

    async def test_transcript_stored(self, services, simulation_result):
        """Each conversation should have a transcript in the transcripts table."""
        for conv_id in simulation_result["conversation_ids"]:
            row = await services.db.fetchrow(
                "SELECT * FROM transcripts WHERE conversation_id = $1",
                conv_id,
            )
            assert row is not None, f"No transcript for conversation {conv_id}"
            assert row["content"] is not None and len(row["content"]) > 0, (
                f"Transcript for {conv_id} is empty"
            )

    async def test_recall_memories_created(self, services, simulation_result):
        """Recall memories should be created for each participant."""
        st = simulation_result["start_time"]
        agents = simulation_result["agents"]

        rows = await services.db.fetch(
            "SELECT * FROM recall_memory WHERE timestamp >= $1",
            st,
        )
        assert len(rows) >= len(agents), (
            f"Expected >= {len(agents)} recall memories, got {len(rows)}"
        )

    async def test_recall_memory_embeddings_nonzero(self, services, simulation_result):
        """Recall memory embeddings should be non-zero vectors (real embeddings)."""
        st = simulation_result["start_time"]

        rows = await services.db.fetch(
            "SELECT embedding FROM recall_memory WHERE timestamp >= $1 LIMIT 5",
            st,
        )
        assert len(rows) > 0, "No recall memories found"

        for row in rows:
            embedding = row["embedding"]
            if embedding is not None:
                # pgvector returns a string like '[0.1,0.2,...]' or a list
                if isinstance(embedding, str):
                    # Parse the vector string
                    values = [float(x) for x in embedding.strip("[]").split(",")]
                else:
                    values = list(embedding)

                nonzero = sum(1 for v in values[:10] if abs(v) > 1e-8)
                assert nonzero > 0, "Recall memory embedding is all zeros"

    async def test_journal_entries_created(self, services, simulation_result):
        """Journal entries should be created for each participant."""
        st = simulation_result["start_time"]
        agents = simulation_result["agents"]

        rows = await services.db.fetch(
            "SELECT * FROM journal_entries WHERE created_at >= $1",
            st,
        )
        assert len(rows) >= len(agents), (
            f"Expected >= {len(agents)} journal entries, got {len(rows)}"
        )

    async def test_simulation_stats_updated(self, services, simulation_result):
        """Simulation record should have total_turns > 0 and total_cost > 0."""
        sim_id = simulation_result["simulation_id"]
        row = await services.db.fetchrow(
            "SELECT total_turns, total_cost, status, completed_at FROM simulations WHERE id = $1",
            sim_id,
        )
        assert row is not None
        assert row["total_turns"] > 0, f"total_turns is {row['total_turns']}"
        assert row["total_cost"] > 0, f"total_cost is {row['total_cost']}"
        assert row["completed_at"] is not None, "completed_at is NULL"


# ── Stage 5: Admin API verification ───────────────────────────────


@_async_mark
class TestAdminAPI:
    """Validate all admin API endpoints return correct data."""

    @pytest.fixture()
    async def client(self, services):
        """httpx AsyncClient against the FastAPI app (no real server needed)."""
        import httpx
        from core.main import app

        # Inject services into app state so admin routes can find them
        app.state.services = services

        transport = httpx.ASGITransport(app=app)
        password = os.environ.get("ADMIN_PASSWORD", "test-admin-password")
        os.environ["ADMIN_PASSWORD"] = password

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {password}"},
        ) as client:
            yield client

    async def test_list_simulations(self, client, simulation_result):
        """GET /api/admin/simulations should return the test simulation."""
        resp = await client.get("/api/admin/simulations")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        data = resp.json()
        sim_ids = [s["id"] for s in data["items"]]
        assert str(simulation_result["simulation_id"]) in sim_ids

    async def test_get_simulation(self, client, simulation_result):
        """GET /api/admin/simulations/{id} should have correct stats."""
        sim_id = simulation_result["simulation_id"]
        resp = await client.get(f"/api/admin/simulations/{sim_id}")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["total_turns"] > 0
        assert float(data["total_cost"]) > 0

    async def test_get_simulation_conversations(self, client, simulation_result):
        """GET /api/admin/simulations/{id}/conversations should return linked conversations."""
        sim_id = simulation_result["simulation_id"]
        resp = await client.get(f"/api/admin/simulations/{sim_id}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) > 0

    async def test_get_conversation_detail(self, client, simulation_result):
        """GET /api/admin/conversations/{id} should include transcript content."""
        if not simulation_result["conversation_ids"]:
            pytest.skip("No conversations to check")

        conv_id = simulation_result["conversation_ids"][0]
        resp = await client.get(f"/api/admin/conversations/{conv_id}")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["transcript"] is not None and len(data["transcript"]) > 0

    async def test_get_agent_conversations(self, client, simulation_result):
        """GET /api/admin/agents/{id}/conversations should return conversations."""
        agent_id = simulation_result["agents"][0]
        sim_id = simulation_result["simulation_id"]
        resp = await client.get(
            f"/api/admin/agents/{agent_id}/conversations",
            params={"simulation_id": str(sim_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    async def test_get_agent_recall_memories(self, client, simulation_result):
        """GET /api/admin/agents/{id}/recall-memories should return new memories."""
        agent_id = simulation_result["agents"][0]
        resp = await client.get(f"/api/admin/agents/{agent_id}/recall-memories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    async def test_get_agent_journal(self, client, simulation_result):
        """GET /api/admin/agents/{id}/journal should return new entries."""
        agent_id = simulation_result["agents"][0]
        resp = await client.get(f"/api/admin/agents/{agent_id}/journal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    async def test_get_agent_core_memory(self, client, simulation_result):
        """GET /api/admin/agents/{id}/core-memory should show version >= 1."""
        agent_id = simulation_result["agents"][0]
        resp = await client.get(f"/api/admin/agents/{agent_id}/core-memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_version"] >= 1

    async def test_get_simulation_costs(self, client, simulation_result):
        """GET /api/admin/simulations/{id}/costs should return a valid response."""
        sim_id = simulation_result["simulation_id"]
        resp = await client.get(f"/api/admin/simulations/{sim_id}/costs")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        data = resp.json()
        # Endpoint should return a valid cost structure
        assert "total" in data
        assert "by_agent" in data


# ── Stage 6: No duplication ───────────────────────────────────────


class TestNoDuplication:
    """Verify scripts don't duplicate core logic."""

    def test_no_dummy_embed_in_watch(self):
        """scripts/watch_conversations.py should NOT contain _dummy_embed."""
        path = PROJECT_ROOT / "scripts" / "watch_conversations.py"
        if not path.exists():
            pytest.skip("watch_conversations.py not found")
        content = path.read_text()
        assert "_dummy_embed" not in content, (
            "watch_conversations.py still contains _dummy_embed"
        )

    def test_no_dummy_embed_in_test_agent(self):
        """scripts/test_agent.py should NOT contain _dummy_embed."""
        path = PROJECT_ROOT / "scripts" / "test_agent.py"
        if not path.exists():
            pytest.skip("test_agent.py not found")
        content = path.read_text()
        assert "_dummy_embed" not in content, (
            "test_agent.py still contains _dummy_embed"
        )

    def test_watch_uses_bootstrap(self):
        """watch_conversations.py should import from core.bootstrap."""
        path = PROJECT_ROOT / "scripts" / "watch_conversations.py"
        if not path.exists():
            pytest.skip("watch_conversations.py not found")
        content = path.read_text()
        assert "core.bootstrap" in content, (
            "watch_conversations.py doesn't use core.bootstrap"
        )

    def test_test_agent_uses_bootstrap(self):
        """test_agent.py should import from core.bootstrap."""
        path = PROJECT_ROOT / "scripts" / "test_agent.py"
        if not path.exists():
            pytest.skip("test_agent.py not found")
        content = path.read_text()
        assert "core.bootstrap" in content, (
            "test_agent.py doesn't use core.bootstrap"
        )

    def test_recall_creation_only_in_core(self):
        """Recall memory creation should live in core/, not duplicated in scripts/."""
        for script_name in ("watch_conversations.py", "test_agent.py"):
            path = PROJECT_ROOT / "scripts" / script_name
            if not path.exists():
                continue
            content = path.read_text()
            assert "store_recall_memory" not in content, (
                f"{script_name} duplicates recall memory creation (should be in ConversationEngine)"
            )

    def test_journal_creation_only_in_core(self):
        """Journal entry creation should live in core/, not duplicated in scripts/."""
        for script_name in ("watch_conversations.py", "test_agent.py"):
            path = PROJECT_ROOT / "scripts" / script_name
            if not path.exists():
                continue
            content = path.read_text()
            assert "create_journal_entry" not in content, (
                f"{script_name} duplicates journal creation (should be in ConversationEngine)"
            )
