#!/usr/bin/env python3
"""Analyze Minecraft bot logs for intent-to-command reliability.

The analyzer is intentionally heuristic: Mindcraft logs are not a stable
machine contract, so this script looks for conservative action-command,
parser, execution, and verification markers in per-bot stdout/stderr logs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_MIN_INTENT_TO_COMMAND = 0.6
DEFAULT_MIN_PARSE_SUCCESS = 0.8
DEFAULT_MIN_EXECUTION_RATE = 0.7
DEFAULT_MIN_VERIFIED_SUCCESS = 0.5
DEFAULT_MIN_INTENTS = 5
DEFAULT_TOP_N = 3

COMMAND_RE = re.compile(r"!\w+\s*\(")
INTENT_VERB_RE = re.compile(
    r"\b(?:place|placing|put|break|breaking|build|building|move|moving|go|walk|"
    r"navigate|collect|gather|search|find|mine|mining|dig|digging|craft|make|"
    r"chop|harvest|inspect|observe|inventory|scout|torch|light)\b",
    re.IGNORECASE,
)
INTENT_PROMISE_RE = re.compile(
    r"\b(?:i(?:'|\u2019)ll|i will|i am going to|i(?:'|\u2019)m going to|we(?:'|\u2019)ll|"
    r"we will|we are going to|let(?:'|\u2019)s|plan to|planning to|about to|"
    r"need to|want to|try to|trying to|start(?:ing)? to|going to|will)\b",
    re.IGNORECASE,
)
UTTERANCE_RE = re.compile(
    r"(^|\b)(?:chat|says?|said|assistant|bot response|llm response|minecraft chat)\b"
    r"|^\s*(?:\[[^\]]+\]\s*)?[A-Za-z][A-Za-z0-9_-]{1,24}\s*[:>]",
    re.IGNORECASE,
)
INSTRUCTION_RE = re.compile(
    r"\b(?:init prompt|init_message|system prompt|settings|profile|blocked_actions|"
    r"available commands|command syntax|good early commands|usage|description)\b",
    re.IGNORECASE,
)

PARSER_FAILURE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "empty_response",
        (
            re.compile(r"\bempty\s+(?:parsed\s+)?(?:llm\s+)?response\b", re.IGNORECASE),
            re.compile(r"\bblank\s+(?:llm\s+)?response\b", re.IGNORECASE),
            re.compile(r"\bparsed response\b.*\bempty\b", re.IGNORECASE),
        ),
    ),
    (
        "no_commands_found",
        (
            re.compile(r"\bno commands found\b", re.IGNORECASE),
            re.compile(r"\bno command(?:s)?\s+(?:were\s+)?(?:parsed|detected)\b", re.IGNORECASE),
        ),
    ),
    (
        "unknown_command",
        (
            re.compile(r"\bcommand\s+!?\w+(?:\([^)]*\))?\s+does not exist\b", re.IGNORECASE),
            re.compile(r"\bunknown command\b", re.IGNORECASE),
        ),
    ),
    (
        "argument_error",
        (
            re.compile(
                r"\b(?:argument|arguments|arg|args|parameter|parameters|param|params)\b"
                r".*\b(?:count|type|required|missing|expected|invalid|must be)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:expected|got)\s+\d+\s+(?:argument|arguments|arg|args|parameter|parameters)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\btoo (?:many|few) (?:arguments|args|parameters|params)\b", re.IGNORECASE),
        ),
    ),
    (
        "parse_error",
        (
            re.compile(r"\bcould not parse\b", re.IGNORECASE),
            re.compile(r"\berror parsing\b", re.IGNORECASE),
            re.compile(r"\bparse error\b", re.IGNORECASE),
            re.compile(r"\bmalformed (?:command|response|parsed response)\b", re.IGNORECASE),
            re.compile(r"\binvalid command syntax\b", re.IGNORECASE),
        ),
    ),
)

ACTION_CONTEXT_RE = re.compile(
    r"\[(?:place|break|move|navigate|build|observe|run_errand|execute_code) trace="
    r"|\baction\.result\b|\bperception\.report\b|\bcode output\b|\baction failed\b"
    r"|\b(?:place|break|move|navigate|build|observe|run_errand)\s+[A-Za-z0-9_-]+\s+",
    re.IGNORECASE,
)
EXECUTION_SUCCESS_RE = re.compile(
    r"\b(?:code output|successfully|status\s*[:=]\s*success|status['\"]?\s*:\s*['\"]success|"
    r"placed|removed|reached|moved|broke)\b",
    re.IGNORECASE,
)
EXECUTION_FAILURE_RE = re.compile(
    r"\b(?:action failed|failed|error|status\s*[:=]\s*(?:failure|partial)|"
    r"status['\"]?\s*:\s*['\"](?:failure|partial)|blocked|invalid|protected|"
    r"timed[- ]out|timeout|unreachable)\b",
    re.IGNORECASE,
)
VERIFICATION_RE = re.compile(
    r"\bbefore=.*\bafter=|\bdistance_to_target=.*\bdelta=|"
    r"\bsteps_verified\s*[:=]\s*[1-9]|\bverified\s*[:=]\s*[1-9]|"
    r"\b(?:placed|removed|reached):\s*(?:position|distance)",
    re.IGNORECASE,
)


@dataclass
class Example:
    line: int
    text: str
    klass: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"line": self.line, "text": self.text}
        if self.klass:
            data["class"] = self.klass
        return data


@dataclass
class AgentStats:
    agent: str
    log_file: str
    intent_utterances: int = 0
    emitted_commands: int = 0
    parser_failures: Counter[str] = field(default_factory=Counter)
    execution_successes: int = 0
    execution_failures: int = 0
    verified_actions: int = 0
    failed_parse_examples: list[Example] = field(default_factory=list)
    verified_success_examples: list[Example] = field(default_factory=list)
    intent_examples: list[Example] = field(default_factory=list)

    @property
    def parse_failures(self) -> int:
        return sum(self.parser_failures.values())

    @property
    def intended_action_events(self) -> int:
        return max(self.intent_utterances, self.emitted_commands)

    @property
    def command_executions(self) -> int:
        return self.execution_successes + self.execution_failures

    @property
    def parse_successes(self) -> int:
        return max(0, self.emitted_commands - self.parse_failures)

    def metrics(self) -> dict[str, float]:
        if self.intent_utterances > 0:
            intent_to_command = min(1.0, self.emitted_commands / self.intent_utterances)
        elif self.emitted_commands > 0:
            intent_to_command = 1.0
        else:
            intent_to_command = 1.0

        parse_total = self.parse_successes + self.parse_failures
        if parse_total > 0:
            parse_success_rate = self.parse_successes / parse_total
        else:
            parse_success_rate = 0.0 if self.intended_action_events else 1.0

        if self.emitted_commands > 0:
            command_execution_rate = min(1.0, self.command_executions / self.emitted_commands)
        else:
            command_execution_rate = 0.0 if self.intended_action_events else 1.0

        if self.execution_successes > 0:
            verified_success_rate = self.verified_actions / self.execution_successes
        else:
            verified_success_rate = 0.0 if self.intended_action_events else 1.0

        return {
            "intent_to_command_ratio": round(intent_to_command, 4),
            "parse_success_rate": round(parse_success_rate, 4),
            "command_execution_rate": round(command_execution_rate, 4),
            "verified_success_rate": round(verified_success_rate, 4),
        }

    def counts(self) -> dict[str, int]:
        return {
            "intent_utterances": self.intent_utterances,
            "emitted_commands": self.emitted_commands,
            "intended_action_events": self.intended_action_events,
            "parse_successes": self.parse_successes,
            "parse_failures": self.parse_failures,
            "command_executions": self.command_executions,
            "execution_successes": self.execution_successes,
            "execution_failures": self.execution_failures,
            "verified_actions": self.verified_actions,
        }

    def to_json(self, top_n: int) -> dict[str, Any]:
        return {
            "log_file": self.log_file,
            "counts": self.counts(),
            "metrics": self.metrics(),
            "parser_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in self.parser_failures.most_common(top_n)
            ],
            "examples": {
                "failed_parses": [example.to_json() for example in self.failed_parse_examples[:top_n]],
                "verified_successes": [
                    example.to_json() for example in self.verified_success_examples[:top_n]
                ],
                "intent_without_command": [example.to_json() for example in self.intent_examples[:top_n]],
            },
        }


def excerpt(line: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", line.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def classify_parser_failure(line: str) -> str | None:
    for klass, patterns in PARSER_FAILURE_PATTERNS:
        if any(pattern.search(line) for pattern in patterns):
            return klass
    return None


def is_potential_utterance(line: str) -> bool:
    if INSTRUCTION_RE.search(line):
        return False
    lower = line.lower()
    blocked_fragments = (
        "management_review_event",
        "trace=",
        "action.result",
        "perception.report",
        "cost_events",
        "preflight",
        "settings_json",
    )
    if any(fragment in lower for fragment in blocked_fragments):
        return False
    return bool(UTTERANCE_RE.search(line))


def is_intent_without_command(line: str) -> bool:
    if COMMAND_RE.search(line):
        return False
    if classify_parser_failure(line):
        return False
    if not is_potential_utterance(line):
        return False
    return bool(INTENT_PROMISE_RE.search(line) and INTENT_VERB_RE.search(line))


def classify_execution(line: str) -> tuple[str | None, bool]:
    if classify_parser_failure(line):
        return None, False
    has_context = bool(ACTION_CONTEXT_RE.search(line))
    has_failure = bool(EXECUTION_FAILURE_RE.search(line))
    has_success = bool(EXECUTION_SUCCESS_RE.search(line))
    if has_failure and (has_context or has_success):
        return "failure", False
    if has_success and (has_context or VERIFICATION_RE.search(line)):
        return "success", bool(VERIFICATION_RE.search(line))
    return None, False


def analyze_log(path: Path, top_n: int) -> AgentStats:
    stats = AgentStats(agent=path.stem, log_file=str(path))
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if INSTRUCTION_RE.search(line):
                command_count = 0
            else:
                command_count = len(COMMAND_RE.findall(line))
            stats.emitted_commands += command_count

            parser_failure = classify_parser_failure(line)
            if parser_failure:
                stats.parser_failures[parser_failure] += 1
                if len(stats.failed_parse_examples) < top_n:
                    stats.failed_parse_examples.append(
                        Example(line=line_no, klass=parser_failure, text=excerpt(line))
                    )
                continue

            if is_intent_without_command(line):
                stats.intent_utterances += 1
                if len(stats.intent_examples) < top_n:
                    stats.intent_examples.append(Example(line=line_no, text=excerpt(line)))

            execution_kind, verified = classify_execution(line)
            if execution_kind == "success":
                stats.execution_successes += 1
                if verified:
                    stats.verified_actions += 1
                    if len(stats.verified_success_examples) < top_n:
                        stats.verified_success_examples.append(Example(line=line_no, text=excerpt(line)))
            elif execution_kind == "failure":
                stats.execution_failures += 1

    return stats


def threshold_violations(
    agent: str,
    stats: AgentStats,
    thresholds: dict[str, float | int],
) -> list[dict[str, Any]]:
    if stats.intended_action_events < int(thresholds["min_intents"]):
        return []

    metrics = stats.metrics()
    checks = (
        ("intent_to_command_ratio", "min_intent_to_command"),
        ("parse_success_rate", "min_parse_success"),
        ("command_execution_rate", "min_execution_rate"),
        ("verified_success_rate", "min_verified_success"),
    )
    violations: list[dict[str, Any]] = []
    for metric_name, threshold_name in checks:
        observed = metrics[metric_name]
        required = float(thresholds[threshold_name])
        if observed + 1e-9 < required:
            violations.append(
                {
                    "agent": agent,
                    "metric": metric_name,
                    "observed": observed,
                    "required": required,
                    "intended_action_events": stats.intended_action_events,
                }
            )
    return violations


def aggregate_stats(agent_stats: list[AgentStats]) -> AgentStats:
    aggregate = AgentStats(agent="aggregate", log_file="<aggregate>")
    for stats in agent_stats:
        aggregate.intent_utterances += stats.intent_utterances
        aggregate.emitted_commands += stats.emitted_commands
        aggregate.parser_failures.update(stats.parser_failures)
        aggregate.execution_successes += stats.execution_successes
        aggregate.execution_failures += stats.execution_failures
        aggregate.verified_actions += stats.verified_actions
    return aggregate


def analyze_run(
    run_dir: Path,
    thresholds: dict[str, float | int],
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    bots_dir = run_dir / "bots"
    if not bots_dir.is_dir():
        raise FileNotFoundError(f"missing bot log directory: {bots_dir}")
    log_paths = sorted(bots_dir.glob("*.log"))
    if not log_paths:
        raise FileNotFoundError(f"no bot logs found in {bots_dir}")

    agent_stats = [analyze_log(path, top_n=top_n) for path in log_paths]
    aggregate = aggregate_stats(agent_stats)
    violations: list[dict[str, Any]] = []
    agents: dict[str, Any] = {}
    for stats in agent_stats:
        agent_violations = threshold_violations(stats.agent, stats, thresholds)
        violations.extend(agent_violations)
        data = stats.to_json(top_n)
        data["threshold_violations"] = agent_violations
        agents[stats.agent] = data

    return {
        "run_dir": str(run_dir),
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "acceptable": not violations,
        "thresholds": thresholds,
        "agents": agents,
        "aggregate": {
            "counts": aggregate.counts(),
            "metrics": aggregate.metrics(),
            "parser_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in aggregate.parser_failures.most_common(top_n)
            ],
        },
        "threshold_violations": violations,
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def render_examples(title: str, examples: list[dict[str, Any]]) -> list[str]:
    lines = [f"#### {title}"]
    if not examples:
        lines.append("none captured")
        return lines
    for example in examples:
        klass = f" [{example['class']}]" if "class" in example else ""
        text = example["text"].replace("`", "'")
        lines.append(f"- line {example['line']}{klass}: `{text}`")
    return lines


def render_markdown(data: dict[str, Any]) -> str:
    thresholds = data["thresholds"]
    lines = [
        "# Action-Command Reliability Report",
        "",
        f"Run directory: `{data['run_dir']}`",
        f"Generated UTC: `{data['generated_at_utc']}`",
        f"Status: **{'PASS' if data['acceptable'] else 'NOT ACCEPTABLE'}**",
        "",
        "## Thresholds",
        "",
        markdown_table(
            ["Metric", "Minimum"],
            [
                ["intent_to_command_ratio", thresholds["min_intent_to_command"]],
                ["parse_success_rate", thresholds["min_parse_success"]],
                ["command_execution_rate", thresholds["min_execution_rate"]],
                ["verified_success_rate", thresholds["min_verified_success"]],
                ["min_intents", thresholds["min_intents"]],
            ],
        ),
        "",
        "## Aggregate",
        "",
        markdown_table(
            ["Metric", "Value"],
            [[name, value] for name, value in data["aggregate"]["metrics"].items()],
        ),
        "",
        markdown_table(
            ["Count", "Value"],
            [[name, value] for name, value in data["aggregate"]["counts"].items()],
        ),
        "",
        "## Top Parser Failure Classes",
        "",
    ]
    parser_classes = data["aggregate"]["parser_failure_classes"]
    if parser_classes:
        lines.append(markdown_table(["Class", "Count"], [[item["class"], item["count"]] for item in parser_classes]))
    else:
        lines.append("none captured")

    lines.extend(["", "## Threshold Violations", ""])
    if data["threshold_violations"]:
        lines.append(
            markdown_table(
                ["Agent", "Metric", "Observed", "Required", "Intended events"],
                [
                    [
                        item["agent"],
                        item["metric"],
                        item["observed"],
                        item["required"],
                        item["intended_action_events"],
                    ]
                    for item in data["threshold_violations"]
                ],
            )
        )
    else:
        lines.append("none")

    lines.extend(["", "## Agents", ""])
    for agent, stats in sorted(data["agents"].items()):
        lines.extend(
            [
                f"### {agent}",
                "",
                markdown_table(["Metric", "Value"], [[name, value] for name, value in stats["metrics"].items()]),
                "",
                markdown_table(["Count", "Value"], [[name, value] for name, value in stats["counts"].items()]),
                "",
            ]
        )
        lines.extend(render_examples("Failed Parse Examples", stats["examples"]["failed_parses"]))
        lines.append("")
        lines.extend(render_examples("Verified Success Examples", stats["examples"]["verified_successes"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(run_dir: Path, data: dict[str, Any]) -> None:
    (run_dir / "action-reliability.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "action-reliability.md").write_text(render_markdown(data), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze per-bot Minecraft logs for action-command reliability.",
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak run directory containing bots/*.log")
    parser.add_argument(
        "--min-intent-to-command",
        type=float,
        default=DEFAULT_MIN_INTENT_TO_COMMAND,
        help=f"Minimum commands per intended-action utterance. Default: {DEFAULT_MIN_INTENT_TO_COMMAND}",
    )
    parser.add_argument(
        "--min-parse-success",
        type=float,
        default=DEFAULT_MIN_PARSE_SUCCESS,
        help=f"Minimum parse success rate. Default: {DEFAULT_MIN_PARSE_SUCCESS}",
    )
    parser.add_argument(
        "--min-execution-rate",
        type=float,
        default=DEFAULT_MIN_EXECUTION_RATE,
        help=f"Minimum command execution rate. Default: {DEFAULT_MIN_EXECUTION_RATE}",
    )
    parser.add_argument(
        "--min-verified-success",
        type=float,
        default=DEFAULT_MIN_VERIFIED_SUCCESS,
        help=f"Minimum verified success rate. Default: {DEFAULT_MIN_VERIFIED_SUCCESS}",
    )
    parser.add_argument(
        "--min-intents",
        type=int,
        default=DEFAULT_MIN_INTENTS,
        help=f"Only enforce thresholds for agents with at least this many intended events. Default: {DEFAULT_MIN_INTENTS}",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help=f"Examples/failure classes to retain. Default: {DEFAULT_TOP_N}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    thresholds: dict[str, float | int] = {
        "min_intent_to_command": args.min_intent_to_command,
        "min_parse_success": args.min_parse_success,
        "min_execution_rate": args.min_execution_rate,
        "min_verified_success": args.min_verified_success,
        "min_intents": args.min_intents,
    }
    try:
        data = analyze_run(args.run_dir, thresholds=thresholds, top_n=args.top_n)
        write_artifacts(args.run_dir, data)
    except Exception as exc:
        print(f"action reliability analysis failed: {exc}", file=sys.stderr)
        return 2

    if data["acceptable"]:
        print(f"ok action-command reliability passed; see {args.run_dir / 'action-reliability.md'}")
        return 0

    print(
        f"x action-command reliability below threshold; see {args.run_dir / 'action-reliability.md'}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
