"""Shared Mindcraft bot-log parsing helpers.

Mindcraft stdout is human-oriented and frequently repeats the same command in
different phases. This module keeps the soak reliability gate and the monitor
aligned on the important distinction: generated text is LLM telemetry, accepted
commands are action intent, and ``Agent executed`` blocks are action results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from _minecraft_log_patterns import COMMAND_CALL_RE

LLM_AWAIT_RE = re.compile(r"Awaiting LM Studio response from model (?P<model>.+)")
LLM_GENERATED_RE = re.compile(r"Generated response:\s*(?P<response>.*)")
STALE_GENERATION_RE = re.compile(
    r"received new message while generating,\s*discarding old response", re.IGNORECASE
)
FULL_RESPONSE_RE = re.compile(r"full response .*?:\s*\"\"(?P<response>.*)\"\"")
PARSED_COMMAND_RE = re.compile(
    r"parsed command:\s*\{\s*commandName:\s*['\"](?P<name>!\w+)['\"]"
    r"(?:,\s*args:\s*\[(?P<args>.*?)\])?",
)
AGENT_EXECUTED_RE = re.compile(r"Agent executed:\s*(?P<name>!\w+)\s+and got:\s*(?P<rest>.*)")

SUCCESS_PATTERNS = (
    re.compile(r"\bPlaced\s+\w+\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bBroke\s+.+?\s+at\b", re.IGNORECASE),
    re.compile(r"\balready\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bYou have reached\b", re.IGNORECASE),
    re.compile(r"\breached:\s*distance_to_target\b", re.IGNORECASE),
    re.compile(r"\bFound\s+.+?\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bCollected\s+\d+\s+\w+\b", re.IGNORECASE),
    re.compile(r"\bsuccess:\s*intended=", re.IGNORECASE),
    re.compile(r"\bNEARBY_BLOCKS\b"),
    re.compile(r"\bCRAFTABLE_ITEMS\b"),
    re.compile(r"\bINVENTORY\b"),
)
VERIFICATION_PATTERNS = (
    re.compile(r"\bPlaced\s+\w+\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bBroke\s+.+?\s+at\b", re.IGNORECASE),
    re.compile(r"\balready\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bbefore=.*\bafter=", re.IGNORECASE),
    re.compile(r"\bdistance_to_target=.*\bdelta=", re.IGNORECASE),
    re.compile(r"\bverified\s*[:=]\s*[1-9]", re.IGNORECASE),
    re.compile(r"\bYou have reached\b", re.IGNORECASE),
    re.compile(r"\bFound\s+.+?\s+at\s+\(", re.IGNORECASE),
    re.compile(r"\bCollected\s+\d+\s+\w+\b", re.IGNORECASE),
)
FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "unsupported_arg_type",
        re.compile(r"\bunknown\s+type:\s*object\b|\bunsupported_arg_type\b|\binvalid_args\b", re.I),
    ),
    (
        "wrong_args",
        re.compile(r"\bwrong_args\b|\bCommand\s+!\w+\s+was given\b|\brequires\s+\d+\s+args?\b"),
    ),
    ("missing_inventory", re.compile(r"\bDon'?t have\b|\bmissing\b.*\binventory\b", re.I)),
    ("placement_blocked", re.compile(r"\bFailed to place\b", re.IGNORECASE)),
    ("interrupted", re.compile(r"\bPathStopped\b|\bpath was stopped\b|\binterrupted\b", re.I)),
    ("undefined_result", re.compile(r"\bgot:\s*undefined\b|\bundefined\b", re.IGNORECASE)),
    ("timeout", re.compile(r"\btimed[- ]out\b|\btimeout\b|\btook too? long\b", re.I)),
    ("unreachable", re.compile(r"\bunreachable\b|\bno path\b", re.IGNORECASE)),
    ("blocked", re.compile(r"\bblocked\b|\bprotected\b|\binvalid\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class ParsedCommand:
    line: int
    name: str
    text: str
    args: str = ""
    source: str = "parsed"
    generation_line: int | None = None


@dataclass
class ParsedGeneration:
    line: int
    response_text: str
    request_line: int | None = None
    model: str = "unknown"
    stale: bool = False
    commands: list[ParsedCommand] = field(default_factory=list)

    @property
    def command_count(self) -> int:
        return len(self.commands)


@dataclass(frozen=True)
class ParsedExecution:
    line: int
    end_line: int
    name: str
    action: str
    detail: str
    outcome: str
    outcome_class: str
    verified: bool
    generation_line: int | None = None


@dataclass(frozen=True)
class BotLogParse:
    generations: list[ParsedGeneration]
    accepted_commands: list[ParsedCommand]
    executions: list[ParsedExecution]

    @property
    def generated_commands(self) -> int:
        return sum(generation.command_count for generation in self.generations)

    @property
    def discarded_commands(self) -> int:
        return sum(
            generation.command_count for generation in self.generations if generation.stale
        )


def command_text(name: str, args: str = "") -> str:
    clean_name = name if name.startswith("!") else f"!{name}"
    clean_args = args.strip()
    return f"{clean_name}({clean_args})" if clean_args else clean_name


def canonical_args(args: str) -> str:
    return re.sub(r"\s+", "", args.replace("'", '"').strip())


def commands_from_text(text: str, *, line: int, source: str, generation_line: int | None) -> list[ParsedCommand]:
    commands: list[ParsedCommand] = []
    for match in COMMAND_CALL_RE.finditer(text):
        name = f"!{match.group('name')}"
        args = (match.group("args") or "").strip()
        commands.append(
            ParsedCommand(
                line=line,
                name=name,
                args=args,
                text=command_text(name, args),
                source=source,
                generation_line=generation_line,
            )
        )
    return commands


def normalize_parsed_args(raw: str | None) -> str:
    if raw is None:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def is_execution_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    prefixes = (
        "Saved memory to:",
        "selected examples:",
        "Awaiting LM Studio",
        "Generated response:",
        "Memory updated to:",
        "full response",
        "Received.",
        "Storing memories",
        "no response",
        "parsed command:",
        "executing code",
    )
    if stripped.startswith(prefixes):
        return True
    if re.search(r"\bfull response\b", stripped, re.IGNORECASE):
        return True
    if AGENT_EXECUTED_RE.search(stripped):
        return True
    return re.search(r"\breceived message from\b", stripped, re.IGNORECASE) is not None


def classify_execution_block(lines: list[str]) -> tuple[str, str, bool]:
    text = "\n".join(lines)
    for outcome_class, pattern in FAILURE_PATTERNS:
        if pattern.search(text):
            return "failure", outcome_class, False
    if any(pattern.search(text) for pattern in SUCCESS_PATTERNS):
        verified = any(pattern.search(text) for pattern in VERIFICATION_PATTERNS)
        return "success", "verified" if verified else "ok", verified
    return "unknown", "unknown", False


def execution_detail(lines: list[str], *, limit: int = 600) -> str:
    detail = re.sub(r"\s+", " ", "\n".join(line.strip() for line in lines).strip())
    if len(detail) <= limit:
        return detail
    return detail[: limit - 3].rstrip() + "..."


def parse_bot_log_lines(lines: list[str]) -> BotLogParse:
    generations: list[ParsedGeneration] = []
    accepted_commands: list[ParsedCommand] = []
    executions: list[ParsedExecution] = []
    pending_requests: list[tuple[int, str]] = []
    current_generation: ParsedGeneration | None = None
    accepted_keys: set[tuple[int | None, str, str]] = set()

    def add_command(command: ParsedCommand) -> None:
        if command.source == "parsed" and command.generation_line is not None:
            if any(
                existing.generation_line == command.generation_line
                and existing.name == command.name
                for existing in accepted_commands
            ):
                return
        command_key = f"{command.name}:{canonical_args(command.args)}"
        key = (
            command.generation_line,
            command_key if command.generation_line is not None else f"{command.line}:{command_key}",
        )
        if key in accepted_keys:
            return
        accepted_keys.add(key)
        accepted_commands.append(command)

    index = 0
    while index < len(lines):
        line_no = index + 1
        line = lines[index]

        awaiting = LLM_AWAIT_RE.search(line)
        if awaiting:
            pending_requests.append((line_no, awaiting.group("model").strip()))

        generated = LLM_GENERATED_RE.search(line)
        if generated:
            request_line, model = pending_requests.pop() if pending_requests else (None, "unknown")
            current_generation = ParsedGeneration(
                line=line_no,
                request_line=request_line,
                model=model,
                response_text=generated.group("response").strip(),
            )
            current_generation.commands.extend(
                commands_from_text(
                    current_generation.response_text,
                    line=line_no,
                    source="generated",
                    generation_line=line_no,
                )
            )
            generations.append(current_generation)

        if STALE_GENERATION_RE.search(line) and current_generation is not None:
            current_generation.stale = True

        parsed = PARSED_COMMAND_RE.search(line)
        if parsed and (current_generation is None or not current_generation.stale):
            name = parsed.group("name")
            args = normalize_parsed_args(parsed.group("args"))
            add_command(
                ParsedCommand(
                    line=line_no,
                    name=name,
                    args=args,
                    text=command_text(name, args),
                    source="parsed",
                    generation_line=current_generation.line if current_generation else None,
                )
            )

        full = FULL_RESPONSE_RE.search(line)
        if full and (current_generation is None or not current_generation.stale):
            for command in commands_from_text(
                full.group("response"),
                line=line_no,
                source="accepted_response",
                generation_line=current_generation.line if current_generation else None,
            ):
                add_command(command)

        if "assistant command:" in line:
            for command in commands_from_text(
                line,
                line=line_no,
                source="assistant_command",
                generation_line=current_generation.line if current_generation else None,
            ):
                add_command(command)

        executed = AGENT_EXECUTED_RE.search(line)
        if executed:
            name = executed.group("name")
            generation_line = current_generation.line if current_generation else None
            block = [line]
            end_index = index
            probe = index + 1
            while probe < len(lines):
                if is_execution_boundary(lines[probe]):
                    break
                block.append(lines[probe])
                end_index = probe
                probe += 1
            outcome, outcome_class, verified = classify_execution_block(block)
            executions.append(
                ParsedExecution(
                    line=line_no,
                    end_line=end_index + 1,
                    name=name,
                    action=name.lstrip("!"),
                    detail=execution_detail(block),
                    outcome=outcome,
                    outcome_class=outcome_class,
                    verified=verified,
                    generation_line=generation_line,
                )
            )
            index = max(index, end_index)

        index += 1

    return BotLogParse(
        generations=generations,
        accepted_commands=accepted_commands,
        executions=executions,
    )


def parse_bot_log_text(text: str) -> BotLogParse:
    return parse_bot_log_lines(text.splitlines())


def parse_bot_log_file(path: Any) -> BotLogParse:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_bot_log_text(handle.read())
