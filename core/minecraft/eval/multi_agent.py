"""Multi-agent timing eval runner for Minecraft command action queues."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME, resolve_profile
from core.minecraft.eval.live_runner import (
    BridgeClient,
    CaseGenerator,
    CommandCase,
    _profile_detail,
    _run_case_for_agent,
    resolve_command_name,
)
from core.minecraft.eval.live_telemetry import (
    CaseResult,
    LiveRunSummary,
    MultiAgentTimingFailure,
    classify_timing_failure,
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One agent cohort member for multi-agent timing evals."""

    agent_id: str
    command_family: str
    cases: int

    def __post_init__(self) -> None:
        agent_id = self.agent_id.strip()
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        if self.cases < 0:
            raise ValueError("agent cases must be non-negative")
        resolve_command_name(self.command_family)
        object.__setattr__(self, "agent_id", agent_id)


@dataclass(frozen=True, slots=True)
class MultiAgentCase:
    """A scheduled command case for one agent."""

    agent_id: str
    case: CommandCase
    scheduled_ts_ms: int

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        if self.scheduled_ts_ms < 0:
            raise ValueError("scheduled_ts_ms must be non-negative")


class MultiAgentScheduler:
    """Create deterministic interleaved cases for a small multi-agent cohort."""

    def __init__(
        self,
        agents: Sequence[AgentSpec],
        *,
        seed: int = 0,
        tick_ms: int = 200,
        stagger_ms: int = 50,
    ) -> None:
        if tick_ms <= 0:
            raise ValueError("tick_ms must be positive")
        if stagger_ms < 0:
            raise ValueError("stagger_ms must be non-negative")
        self.agents = tuple(agents)
        if not self.agents:
            raise ValueError("at least one agent spec is required")
        self.seed = seed
        self.tick_ms = tick_ms
        self.stagger_ms = stagger_ms

    def schedule(self) -> tuple[MultiAgentCase, ...]:
        scheduled: list[tuple[int, int, MultiAgentCase]] = []
        for agent_index, agent in enumerate(self.agents):
            generator = CaseGenerator(
                agent.command_family,
                agent.cases,
                seed=self.seed + (agent_index * 10_000),
            )
            for case_index, case in enumerate(generator.generate()):
                scheduled_ts_ms = (case_index * self.tick_ms) + (agent_index * self.stagger_ms)
                wrapped_case = _wrap_case_for_agent(
                    case,
                    agent_id=agent.agent_id,
                    scheduled_ts_ms=scheduled_ts_ms,
                    tick_ms=self.tick_ms,
                    stagger_ms=self.stagger_ms,
                )
                scheduled.append(
                    (
                        scheduled_ts_ms,
                        agent_index,
                        MultiAgentCase(agent.agent_id, wrapped_case, scheduled_ts_ms),
                    )
                )
        return tuple(item for _, _, item in sorted(scheduled, key=lambda item: item[:2]))


async def run_multi_agent_timing_eval(
    agents: Sequence[AgentSpec],
    *,
    bridge: BridgeClient,
    profile: str = DEFAULT_PROFILE_NAME,
    seed: int = 0,
    env: Mapping[str, str] | None = None,
    project_root: Any | None = None,
    dry_run: bool = False,
    tick_ms: int = 200,
    stagger_ms: int = 50,
    director_fanout: int = 0,
    verbose: bool = False,
) -> LiveRunSummary:
    """Run a deterministic multi-agent action queue timing eval."""

    if director_fanout < 0:
        raise ValueError("director_fanout must be non-negative")
    agent_specs = tuple(agents)
    scheduler = MultiAgentScheduler(
        agent_specs,
        seed=seed,
        tick_ms=tick_ms,
        stagger_ms=stagger_ms,
    )
    scheduled_cases = scheduler.schedule()
    resolved_profile = resolve_profile(profile, env=env, project_root=project_root)

    results: list[CaseResult] = []
    for scheduled_case in scheduled_cases:
        _prepare_bridge_case(
            bridge,
            scheduled_case,
            director_fanout=director_fanout,
        )
        case = _case_with_director_params(scheduled_case.case, director_fanout)
        results.append(
            await _run_case_for_agent(
                case,
                bridge=bridge,
                agent_id=scheduled_case.agent_id,
            )
        )

    profile_detail = _profile_detail(resolved_profile)
    profile_detail["multi_agent"] = _multi_agent_detail(
        agent_specs,
        results,
        tick_ms=tick_ms,
        stagger_ms=stagger_ms,
        director_fanout=director_fanout,
    )
    return LiveRunSummary(
        command="multi-agent-timing",
        resolved_command="multi-agent-timing",
        profile=resolved_profile.name,
        profile_detail=profile_detail,
        seed=seed,
        dry_run=dry_run,
        verbose=verbose,
        case_results=tuple(results),
    )


class MultiAgentFakeBridge:
    """Deterministic bridge responses for multi-agent timing CI tests."""

    def __init__(
        self,
        responses_by_agent: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.responses_by_agent = {
            str(agent_id): tuple(responses)
            for agent_id, responses in (responses_by_agent or {}).items()
        }
        self.calls: list[Mapping[str, Any]] = []
        self._counts: dict[str, int] = {}
        self._current_case: MultiAgentCase | None = None
        self._director_fanout = 0

    def prepare_case(
        self,
        case: MultiAgentCase,
        *,
        director_fanout: int = 0,
    ) -> None:
        self._current_case = case
        self._director_fanout = max(0, director_fanout)

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        case = self._current_case
        agent_id = case.agent_id if case is not None else "agent"
        count = self._counts.get(agent_id, 0)
        self._counts[agent_id] = count + 1
        self.calls.append(
            {
                "agent_id": agent_id,
                "command_text": command_text,
                "count": count,
            }
        )
        response = self._response_for(agent_id, count)
        return _response_with_defaults(
            response,
            agent_id=agent_id,
            action_id=case.case.action_id if case is not None else f"{agent_id}-{count}",
            scheduled_ts_ms=case.scheduled_ts_ms if case is not None else count,
        )

    def _response_for(self, agent_id: str, count: int) -> Mapping[str, Any]:
        responses = self.responses_by_agent.get(agent_id)
        if responses:
            return responses[count % len(responses)]
        return _default_timing_response(count, director_fanout=self._director_fanout)


def _wrap_case_for_agent(
    case: CommandCase,
    *,
    agent_id: str,
    scheduled_ts_ms: int,
    tick_ms: int,
    stagger_ms: int,
) -> CommandCase:
    params = dict(case.params)
    params.update(
        {
            "agent_id": agent_id,
            "multi_agent": True,
            "scheduled_ts_ms": scheduled_ts_ms,
            "tick_ms": tick_ms,
            "stagger_ms": stagger_ms,
            "queue_contention_threshold": 1,
        }
    )
    return CommandCase(
        case_id=f"{agent_id}-{case.case_id}",
        command_name=case.command_name,
        command_text=case.command_text,
        params=params,
    )


def _case_with_director_params(case: CommandCase, director_fanout: int) -> CommandCase:
    if director_fanout <= 0:
        return case
    params = dict(case.params)
    params["director_fanout"] = director_fanout
    return CommandCase(case.case_id, case.command_name, case.command_text, params)


def _prepare_bridge_case(
    bridge: BridgeClient,
    case: MultiAgentCase,
    *,
    director_fanout: int,
) -> None:
    prepare_case = getattr(bridge, "prepare_case", None)
    if callable(prepare_case):
        prepare_case(case, director_fanout=director_fanout)


def _default_timing_response(count: int, *, director_fanout: int) -> Mapping[str, Any]:
    scenario = count % 5
    if scenario == 0:
        return {
            "status": "ok",
            "reason": "completed",
            "queue_depth": 0,
        }
    if scenario == 1:
        return {
            "status": "failed",
            "reason": "blocked by queue contention conflicting action",
            "queue_depth": 3,
            "queue_contention": True,
            "conflicting_action_ids": ("conflict-queue-1",),
        }
    if scenario == 2:
        return {
            "status": "timeout",
            "reason": "self_interruption preempted by newer action",
            "self_interruption_count": 2,
        }
    if scenario == 3:
        return {
            "status": "failed",
            "reason": "blocked by Director fanout duplicate dispatch",
            "director_fanout_count": max(1, director_fanout or 2),
        }
    return {
        "status": "failed",
        "reason": "dropped command_loss blocked by timing window",
        "dropped_commands": 1,
        "command_loss_count": 1,
    }


def _response_with_defaults(
    response: Mapping[str, Any],
    *,
    agent_id: str,
    action_id: str,
    scheduled_ts_ms: int,
) -> Mapping[str, Any]:
    state = response.get("final_state")
    final_state = dict(state) if isinstance(state, Mapping) else {}
    final_state.setdefault("agent_id", agent_id)
    final_state.setdefault("multi_agent", True)
    final_state.setdefault("scheduled_ts_ms", scheduled_ts_ms)
    final_state.setdefault("last_command_ts_ms", scheduled_ts_ms)
    final_state.setdefault("agents", {agent_id: {"scheduled_ts_ms": scheduled_ts_ms}})
    for key in (
        "queue_depth",
        "queue_contention",
        "self_interruption_count",
        "director_fanout_count",
        "dropped_commands",
        "command_loss_count",
        "conflicting_action_ids",
    ):
        if key in response:
            final_state.setdefault(key, response[key])
    action_events = tuple(response.get("action_events") or ())
    if not action_events:
        action_events = _default_action_events(
            response,
            action_id=action_id,
            scheduled_ts_ms=scheduled_ts_ms,
        )
    payload = dict(response)
    payload["final_state"] = final_state
    payload["action_events"] = action_events
    return payload


def _default_action_events(
    response: Mapping[str, Any],
    *,
    action_id: str,
    scheduled_ts_ms: int,
) -> tuple[Mapping[str, Any], ...]:
    if response.get("queue_contention"):
        return (
            {
                "action_id": action_id,
                "kind": "queued",
                "ts_ms": scheduled_ts_ms,
                "payload": {
                    "queue_depth": response.get("queue_depth", 0),
                    "queue_contention": True,
                    "conflicting_action_ids": response.get("conflicting_action_ids", ()),
                },
            },
        )
    if response.get("self_interruption_count"):
        return (
            {
                "action_id": action_id,
                "kind": "interrupted",
                "ts_ms": scheduled_ts_ms,
                "payload": {
                    "self_interruption_count": response.get("self_interruption_count", 1),
                    "message": "self_interruption",
                },
            },
            {
                "action_id": action_id,
                "kind": "preempted",
                "ts_ms": scheduled_ts_ms + 1,
                "payload": {"message": "preempted"},
            },
        )
    if response.get("director_fanout_count"):
        return (
            {
                "action_id": action_id,
                "kind": "fanout",
                "ts_ms": scheduled_ts_ms,
                "payload": {
                    "director_fanout_count": response.get("director_fanout_count", 1),
                    "message": "director_fanout",
                },
            },
        )
    if response.get("dropped_commands") or response.get("command_loss_count"):
        return (
            {
                "action_id": action_id,
                "kind": "dropped",
                "ts_ms": scheduled_ts_ms,
                "payload": {
                    "dropped_commands": response.get("dropped_commands", 1),
                    "command_loss_count": response.get("command_loss_count", 1),
                    "message": "command_loss",
                },
            },
        )
    return ()


def _multi_agent_detail(
    agents: Sequence[AgentSpec],
    results: Sequence[CaseResult],
    *,
    tick_ms: int,
    stagger_ms: int,
    director_fanout: int,
) -> dict[str, Any]:
    return {
        "agents": [
            {
                "agent_id": agent.agent_id,
                "command_family": agent.command_family,
                "cases": agent.cases,
            }
            for agent in agents
        ],
        "tick_ms": tick_ms,
        "stagger_ms": stagger_ms,
        "director_fanout": director_fanout,
        "per_agent_outcome_counts": _per_agent_outcome_counts(results),
        "failure_classes": _failure_class_counts(results),
    }


def _per_agent_outcome_counts(results: Sequence[CaseResult]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for result in results:
        agent_id = result.agent_id or "unknown"
        counts.setdefault(agent_id, Counter())[result.outcome_class] += 1
    return {agent_id: dict(counter) for agent_id, counter in sorted(counts.items())}


def _failure_class_counts(results: Sequence[CaseResult]) -> dict[str, int]:
    counts = {failure: 0 for failure in MultiAgentTimingFailure.ALL}
    for result in results:
        if result.timing is None:
            continue
        counts[classify_timing_failure(result.timing, params=result.params)] += 1
    return counts
