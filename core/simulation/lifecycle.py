"""Shared simulation lifecycle helpers for director and embodied runs."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.event_bus import EventType
from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY, OpenRouterClient
from core.memory.reflection_scheduler import ReflectionScheduler
from core.models import SimulationCreate, SimulationStatus

if TYPE_CHECKING:
    import uuid

logger = logging.getLogger(__name__)


class CostLimitExceededError(Exception):
    """Raised when simulation spending exceeds a configured cost limit."""


class SimulationLifecycleBase:
    """Lifecycle plumbing shared by simulation orchestrators.

    Concrete supervisors provide the dependencies as attributes. This keeps
    seeded/autonomous phase logic separate from embodied runtime supervision
    while preserving one implementation for run IDs, Redis scoping, memory
    seeding, cost checks, and finalization.
    """

    @property
    def simulation_id(self) -> uuid.UUID | None:
        return self._simulation_id

    def cancel(self) -> None:
        """Signal the lifecycle to stop at the next safe point."""
        self._cancelled = True

    def _build_reflection_scheduler(self) -> ReflectionScheduler:
        """Create a ReflectionScheduler from config, falling back to defaults."""
        kwargs: dict[str, int] = {}
        try:
            rc = self._config_loader.config.reflection
            if hasattr(rc, "six_hour_interval_hours") and isinstance(
                rc.six_hour_interval_hours, int
            ):
                kwargs = {
                    "six_hour_interval_hours": rc.six_hour_interval_hours,
                    "daily_hour": rc.daily_hour,
                    "weekly_day": rc.weekly_day,
                }
        except (AttributeError, TypeError):
            pass
        return ReflectionScheduler(self.clock, self._reflection, **kwargs)

    def _rescope_redis(self, sim_id: uuid.UUID) -> None:
        """Create a simulation-scoped Redis and re-wire all services."""
        from core.redis_keys import ScopedRedis

        scoped = ScopedRedis(self._redis, sim_id)

        if self._services:
            if self._services.agent_state_manager is not None:
                self._services.agent_state_manager._redis = scoped
                self._services.agent_state_manager._cache.clear()
            if self._services.shared_working_state is not None:
                self._services.shared_working_state._redis = scoped
            if self._services.goal_manager is not None:
                self._services.goal_manager._redis = scoped
            if self._services.agent_registry is not None:
                self._services.agent_registry._redis = scoped
            if self._services.scoped_redis is not None:
                self._services.scoped_redis = scoped

        if self._proximity is not None:
            self._proximity._redis = scoped
        if self._context is not None:
            self._context._redis = scoped
        if self._management is not None:
            self._management._redis = scoped

        logger.info(
            "Re-scoped Redis for simulation %s (prefix: %s)",
            sim_id,
            scoped._prefix,
        )

    def _scope_services_to_simulation(self, sim_id: uuid.UUID) -> None:
        """Point shared service instances at ``sim_id``."""
        self._rescope_redis(sim_id)

        if self._compactor is not None:
            self._compactor._simulation_id = sim_id
        if self._reflection is not None:
            self._reflection._simulation_id = sim_id
        if self._management is not None:
            self._management._simulation_id = sim_id
        if self._services:
            if self._services.economy_manager is not None:
                self._services.economy_manager.simulation_id = sim_id
            if self._services.alliance_manager is not None:
                self._services.alliance_manager.simulation_id = sim_id
            if self._services.dream_manager is not None:
                self._services.dream_manager._simulation_id = sim_id
            if self._services.event_generator is not None:
                self._services.event_generator.simulation_id = sim_id
            if self._services.agent_state_manager is not None:
                self._services.agent_state_manager.simulation_id = sim_id

    def _build_model_versions(self) -> dict[str, dict[str, str]]:
        """Build a map of agent_id -> {conversation, building} resolved model IDs."""
        versions: dict[str, dict[str, str]] = {}
        for agent_id in self._config.agents:
            agent = self._agents.get_agent(agent_id)
            if agent is None:
                continue
            conv_model = agent.model_conversation
            build_model = agent.model_building
            if isinstance(self._llm, OpenRouterClient):
                versions[agent_id] = {
                    "conversation": self._llm.model_provenance(conv_model),
                    "building": self._llm.model_provenance(build_model),
                }
                continue
            conv_canonical = MODEL_NAME_ALIASES.get(conv_model, conv_model)
            build_canonical = MODEL_NAME_ALIASES.get(build_model, build_model)
            conv_openrouter = (
                MODEL_REGISTRY[conv_canonical].openrouter_id
                if conv_canonical in MODEL_REGISTRY
                else conv_model
            )
            build_openrouter = (
                MODEL_REGISTRY[build_canonical].openrouter_id
                if build_canonical in MODEL_REGISTRY
                else build_model
            )
            versions[agent_id] = {
                "conversation": conv_openrouter,
                "building": build_openrouter,
            }
        return versions

    def _seed_rng(self, simulation_id: uuid.UUID) -> None:
        """Seed the global RNG from the simulation ID for reproducibility."""
        seed = int(hashlib.sha256(str(simulation_id).encode()).hexdigest()[:8], 16)
        random.seed(seed)
        logger.info("RNG seeded with %d (from simulation %s)", seed, simulation_id)

    async def _apply_memory_seed(self, sim_id: uuid.UUID) -> None:
        """Apply ``config.memory_seed`` to ``sim_id`` when configured."""
        if (
            self._config.memory_seed is None
            or self._config.dry_run
            or self._services is None
            or self._services.core_memory is None
            or self._services.recall_memory is None
            or self._memory_repo is None
        ):
            return

        from core.memory.memory_seed import MemorySeedApplier

        applier = MemorySeedApplier(
            db=self._db,
            memory_repo=self._memory_repo,
            core_memory_mgr=self._services.core_memory,
            recall_memory_mgr=self._services.recall_memory,
            agent_registry=self._agents,
            token_counter=self._services.token_counter,
            relationship_repo=self._relationship_repo,
        )
        seed_result = await applier.apply(self._config.memory_seed, sim_id)
        logger.info(
            "Applied memory_seed mode=%s: %d core, %d recall, %d journal for agents %s",
            self._config.memory_seed.mode,
            seed_result.core_memories_restored,
            seed_result.recall_memories_restored,
            seed_result.journal_entries_restored,
            seed_result.agents_restored,
        )
        for warning in seed_result.warnings:
            logger.warning("memory_seed: %s", warning)

    async def _initialize_core_memories(self, sim_id: uuid.UUID) -> None:
        """Create default core memories after any configured seed is applied."""
        if self._services and self._services.core_memory:
            from core.bootstrap import init_core_memories

            initialized = await init_core_memories(
                self._agents,
                self._services.core_memory,
                simulation_id=sim_id,
            )
            if initialized:
                logger.info(
                    "Initialized core memory for %d agents: %s",
                    len(initialized),
                    initialized,
                )

    async def _create_or_attach_simulation(
        self,
        config_snapshot: dict[str, Any],
        model_versions: dict[str, dict[str, str]],
    ) -> Any:
        """Create a simulation row, or attach to one pre-created by the API."""
        import uuid as _uuid

        if self._config.existing_sim_id:
            sim_uuid = _uuid.UUID(self._config.existing_sim_id)
            sim = await self._sim_repo.get(sim_uuid)
            if sim is None:
                raise RuntimeError(f"existing_sim_id {sim_uuid} not found in simulations table")
            await self._sim_repo.update_config(sim_uuid, config_snapshot)
            await self._sim_repo.update_agents_participated(sim_uuid, self._config.agents)
            await self._sim_repo.update_status(sim_uuid, SimulationStatus.running)
            if self._config.factions:
                await self._sim_repo.update_factions(
                    sim_uuid, [f.model_dump() for f in self._config.factions]
                )
            return await self._sim_repo.get(sim_uuid)

        return await self._sim_repo.create(
            SimulationCreate(
                name=self._config.name,
                description=self._config.description,
                config=config_snapshot,
                status=SimulationStatus.running,
                agents_participated=self._config.agents,
                model_versions=model_versions,
                hypothesis=self._config.hypothesis,
                factions=[f.model_dump() for f in self._config.factions],
            )
        )

    async def _start_lifecycle(self, *, label: str) -> Any:
        """Create/attach the simulation row and initialize shared state."""
        self._start_time = time.monotonic()
        config_snapshot = {
            **self._config.to_dict(),
            "clock_state": self.clock.to_dict(),
            "llm_provider": (
                self._llm.provider if isinstance(self._llm, OpenRouterClient) else "openrouter"
            ),
        }
        model_versions = self._build_model_versions()
        sim = await self._create_or_attach_simulation(config_snapshot, model_versions)
        self._simulation_id = sim.id
        self._started_at = sim.started_at or datetime.now(UTC)
        self._llm._simulation_id = sim.id
        if self._selection_logger is not None:
            self._selection_logger.simulation_id = sim.id
        self._seed_rng(sim.id)

        self._errors.clear()
        self._event_bus.on(EventType.SIMULATION_ERROR, self._on_simulation_error)

        logger.info(
            "Created %s simulation %s (%s) with model versions: %s",
            label,
            sim.id,
            sim.name,
            model_versions,
        )
        self._display.show_simulation_start(sim, self._config)

        await self._apply_memory_seed(sim.id)
        await self._initialize_core_memories(sim.id)
        self._scope_services_to_simulation(sim.id)
        return sim

    async def _terminated(self) -> bool:
        """Check cancellation, duration, and kill-switch termination conditions."""
        if self._cancelled:
            return True
        if self._config.duration and self.clock.elapsed() >= self._config.duration:
            logger.info("Duration limit reached (%s)", self._config.duration)
            return True
        if self._redis:
            kill = await self._redis.get(KILL_SWITCH_KEY)
            if kill in {KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_ACTIVE_VALUE.encode()}:
                logger.info("Kill switch activated; stopping simulation")
                return True
        return False

    async def _check_cost_limit(self) -> None:
        """Reconcile authoritative cost_events spend and enforce configured caps."""
        if self._simulation_id is None:
            return
        try:
            actual_cost = await self._sim_repo.get_total_cost_from_events(self._simulation_id)
            if actual_cost > 0 and actual_cost != self._total_cost:
                await self._sim_repo.increment_stats(
                    self._simulation_id,
                    cost=actual_cost - self._total_cost,
                )
                self._total_cost = actual_cost
        except Exception:
            logger.warning(
                "Cost reconciliation failed for %s, using in-memory total $%s",
                self._simulation_id,
                self._total_cost,
                exc_info=True,
            )
        if self._total_cost > self._config.max_cost:
            raise CostLimitExceededError(
                f"Total cost ${self._total_cost} exceeds limit ${self._config.max_cost}"
            )
        if self._config.max_cost_rolling is not None and self._config.rolling_window is not None:
            rolling_cost = await self._sim_repo.get_rolling_cost_from_events(
                self._simulation_id,
                self._config.rolling_window,
            )
            if rolling_cost > self._config.max_cost_rolling:
                raise CostLimitExceededError(
                    f"Rolling spend ${rolling_cost} over {self._config.rolling_window} "
                    f"exceeds limit ${self._config.max_cost_rolling}"
                )

    async def _on_simulation_error(self, event: dict[str, Any]) -> None:
        """Collect runtime errors emitted via SIMULATION_ERROR events."""
        self._errors.append(event)

    async def _finalize(
        self,
        status: SimulationStatus,
        *,
        error_log: dict[str, Any] | None = None,
    ) -> None:
        """Update the simulation record with final status and durations."""
        if self._simulation_id is None:
            return

        combined_log: dict[str, Any] | list[Any] | None = None
        if error_log and self._errors:
            combined_log = {**error_log, "runtime_errors": self._errors}
        elif error_log:
            combined_log = error_log
        elif self._errors:
            combined_log = {"runtime_errors": self._errors}

        self._event_bus.off(
            EventType.SIMULATION_ERROR,
            self._on_simulation_error,
        )

        completed_at = datetime.now(UTC)
        if self._started_at is not None:
            real_duration = completed_at - self._started_at
        else:
            real_duration = timedelta(seconds=time.monotonic() - self._start_time)
        if self._config.speed_multiplier > 0 or self._config.mode == "autonomous":
            simulated_duration = self.clock.elapsed()
        else:
            simulated_duration = timedelta(hours=len(self._config.phases))

        await self._sim_repo.update_status(
            self._simulation_id,
            status.value,
            completed_at=completed_at,
            error_log=combined_log,
        )
        await self._sim_repo.update_durations(
            self._simulation_id,
            simulated_duration=simulated_duration,
            real_duration=real_duration,
        )

        try:
            actual_cost = await self._sim_repo.get_total_cost_from_events(self._simulation_id)
            if actual_cost > 0:
                await self._sim_repo.increment_stats(
                    self._simulation_id,
                    cost=actual_cost - self._total_cost,
                )
                self._total_cost = actual_cost
        except Exception:
            logger.warning(
                "Failed to reconcile cost from cost_events for %s",
                self._simulation_id,
                exc_info=True,
            )

        final_config = {**self._config.to_dict(), "clock_state": self.clock.to_dict()}
        await self._sim_repo.update_config(self._simulation_id, final_config)

        try:
            await self._write_baseline_outcomes(real_duration, simulated_duration)
        except Exception:
            logger.warning(
                "Failed to persist baseline outcomes for %s",
                self._simulation_id,
                exc_info=True,
            )

        sim = await self._sim_repo.get(self._simulation_id)
        if sim:
            self._display.show_summary(sim, real_duration)

        if sim is not None and sim.status in {"completed", "failed"}:
            try:
                await self._enqueue_video_render(sim)
            except Exception:
                logger.warning(
                    "Failed to enqueue video render for %s",
                    self._simulation_id,
                    exc_info=True,
                )

        if sim is not None and sim.submitted_by_user_id is not None:
            try:
                await self._notify_submitter(sim)
            except Exception:
                logger.warning(
                    "Failed to send completion notification for %s",
                    self._simulation_id,
                    exc_info=True,
                )

    async def _enqueue_video_render(self, sim: Any) -> None:
        """Enqueue the headless video render for ``sim``."""
        from core.video.worker import enqueue_render, mark_unrenderable

        if sim.total_turns <= 0 or sim.total_conversations <= 0:
            await mark_unrenderable(
                sim.id,
                sim_repo=self._sim_repo,
                reason="no transcript turns",
            )
            return
        await enqueue_render(sim.id, sim_repo=self._sim_repo)

    async def _notify_submitter(self, sim: Any) -> None:
        """Email the public submitter that their simulation finished."""
        from core.notifications import send_completion_email
        from core.repos.user_repo import UserRepo

        user_repo = UserRepo(self._db)
        user = await user_repo.get_by_id(sim.submitted_by_user_id)
        if user is None:
            logger.info(
                "[notify] submitter %s no longer exists; skipping email",
                sim.submitted_by_user_id,
            )
            return

        video_url = getattr(sim, "video_url", None)
        await send_completion_email(
            sim,
            user,
            user_repo=user_repo,
            video_url=video_url,
        )

    async def _write_baseline_outcomes(
        self,
        real_duration: timedelta,
        simulated_duration: timedelta,
    ) -> None:
        """Populate baseline outcomes JSONB and optional learning summary."""
        if self._simulation_id is None:
            return
        sim = await self._sim_repo.get(self._simulation_id)
        if sim is None:
            return

        evals: dict[str, Any] = {}
        try:
            from core.repos.eval_repo import EvalRepo

            eval_repo = EvalRepo(self._db)
            latest = await eval_repo.get_latest_eval_run(self._simulation_id)
            if latest is not None:
                evals["eval_run_id"] = str(latest.id)
                evals["eval_suite"] = latest.eval_suite
                evals["overall_score"] = (
                    str(latest.overall_score) if latest.overall_score is not None else None
                )
                results = await eval_repo.get_eval_results(latest.id)
                evals["category_scores"] = {
                    r.category: (str(r.score) if r.score is not None else None) for r in results
                }
        except Exception:
            logger.debug("No eval data attached to simulation", exc_info=True)

        outcomes: dict[str, Any] = {
            "key_metrics": {
                "total_conversations": sim.total_conversations,
                "total_turns": sim.total_turns,
                "total_tokens": sim.total_tokens,
                "total_cost": str(sim.total_cost),
                "total_artifacts": sim.total_artifacts,
                "total_management_flags": sim.total_management_flags,
                "simulated_duration_seconds": simulated_duration.total_seconds(),
                "real_duration_seconds": real_duration.total_seconds(),
            },
            "evals": evals,
            "surprises": [],
            "failures": list(self._errors),
        }

        await self._sim_repo.update_research_fields(self._simulation_id, outcomes=outcomes)

        if self._config.auto_draft_learnings and not self._config.dry_run:
            try:
                draft = await self._draft_learning_summary(sim, outcomes)
                if draft:
                    await self._sim_repo.append_learning(
                        self._simulation_id, author="system", text=draft
                    )
            except Exception:
                logger.warning(
                    "Auto-draft learnings failed for %s",
                    self._simulation_id,
                    exc_info=True,
                )

    async def _draft_learning_summary(
        self,
        sim: Any,
        outcomes: dict[str, Any],
    ) -> str | None:
        """Ask the LLM to summarize the run in 2-3 sentences."""
        prompt = (
            "Summarize this simulation run in 2-3 sentences as a research learning. "
            f"Hypothesis: {sim.hypothesis or '(none provided)'}. "
            f"Key metrics: {outcomes['key_metrics']}. "
            f"Eval data: {outcomes['evals']}. "
            f"Failures: {len(outcomes['failures'])}."
        )
        try:
            resp = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model="claude-haiku-4-5",
                max_tokens=200,
            )
        except Exception:
            logger.debug("LLM draft learnings call failed", exc_info=True)
            return None
        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            content = resp.get("content")
        if content is None:
            return None
        text = str(content).strip()
        return text or None
