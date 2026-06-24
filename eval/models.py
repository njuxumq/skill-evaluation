"""Data models for the skill evaluation harness."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional


class Verdict(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    UNSTABLE = "UNSTABLE"


# --- Transcript Event Types ---


@dataclass
class ToolCallEvent:
    tool: str
    input: dict[str, Any] = field(default_factory=dict)

    @property
    def params(self) -> dict[str, Any]:
        return self.input


@dataclass
class TextOutputEvent:
    text: str


Event = ToolCallEvent | TextOutputEvent


# --- ParsedTranscript ---


class ParsedTranscript:
    """Structured transcript with skill scope and turn boundaries.

    All behavior assertions (H1-H9) operate within skill_scope.
    """

    def __init__(self, events: list[Event], turn_boundaries: list[int] | None = None):
        self.events = events
        self._turn_boundaries = turn_boundaries or []
        self._skill_boundary = self._find_skill_boundary()

    def _find_skill_boundary(self) -> int:
        for i, e in enumerate(self.events):
            if isinstance(e, ToolCallEvent) and e.tool == "Skill":
                return i + 1
        return 0

    @property
    def skill_loaded(self) -> bool:
        return any(
            isinstance(e, ToolCallEvent) and e.tool == "Skill"
            for e in self.events
        )

    @property
    def skill_scope(self) -> list[Event]:
        return self.events[self._skill_boundary:]

    @property
    def actions(self) -> list[ToolCallEvent]:
        return [e for e in self.skill_scope if isinstance(e, ToolCallEvent)]

    @property
    def text_outputs(self) -> list[TextOutputEvent]:
        return [e for e in self.skill_scope if isinstance(e, TextOutputEvent)]

    def first_text_output(self) -> str:
        texts = self.text_outputs
        return texts[0].text if texts else ""

    def all_text(self) -> str:
        return "\n".join(e.text for e in self.text_outputs)

    def last_text_output(self) -> str:
        texts = self.text_outputs
        return texts[-1].text if texts else ""

    def turn_text(self, turn_index: int) -> str:
        if turn_index < 0:
            return ""
        # Adjust boundaries relative to skill_scope offset
        offset = self._skill_boundary
        adjusted = [max(0, b - offset) for b in self._turn_boundaries]
        scope = self.skill_scope
        scope_len = len(scope)

        start = adjusted[turn_index] if turn_index < len(adjusted) else scope_len
        end = adjusted[turn_index + 1] if turn_index + 1 < len(adjusted) else scope_len
        start = min(start, scope_len)
        end = min(end, scope_len)

        texts = [
            e.text for e in scope[start:end]
            if isinstance(e, TextOutputEvent)
        ]
        return "\n".join(texts)

    def first_tool_call(self, tool_name: str) -> Optional[ToolCallEvent]:
        for e in self.actions:
            if e.tool == tool_name:
                return e
        return None

    def has_tool_call(self, tool_name: str) -> bool:
        return any(e.tool == tool_name for e in self.actions)

    def tool_call_count(self, tool_name: str) -> int:
        return sum(1 for e in self.actions if e.tool == tool_name)

    def text_before_tool(self, tool_name: str) -> str:
        texts: list[str] = []
        for e in self.skill_scope:
            if isinstance(e, ToolCallEvent) and e.tool == tool_name:
                break
            if isinstance(e, TextOutputEvent):
                texts.append(e.text)
        return "\n".join(texts)


# --- Test Case Models ---


@dataclass
class FollowUp:
    user_input: str
    fixtures_override: dict[str, Any] = field(default_factory=dict)


@dataclass
class CustomAssertion:
    type: str
    pattern: str = ""
    scope: str = "all_text"
    check: str = ""
    tool: str = ""
    tools: list[str] = field(default_factory=list)
    count: Optional[int] = None
    param_path: str = ""
    expected: Any = None


@dataclass
class HardAssertions:
    rules: list[str] = field(default_factory=list)
    custom: list[CustomAssertion] = field(default_factory=list)


@dataclass
class Assertions:
    hard: HardAssertions = field(default_factory=HardAssertions)
    soft: str = "all"


@dataclass
class PreState:
    """Pre-seeded .eval/ files to accelerate stage traversal."""
    session_id: str = ""
    files: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestCase:
    id: str
    name: str
    stage: str
    priority: str
    instruction: str
    fixtures: dict[str, Any] = field(default_factory=dict)
    follow_ups: list[FollowUp] = field(default_factory=list)
    expected_behavior: str = ""
    assertions: Assertions = field(default_factory=Assertions)
    pre_state: Optional[PreState] = None
    runtime: str = "claude-code"
    max_turns: int = 100
    timeout: int = 120

    @classmethod
    def from_yaml(cls, data: dict) -> TestCase:
        required = ("id", "name", "stage", "priority", "instruction")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"TestCase YAML missing required fields: {missing}")

        assertions_raw = data.get("assertions", {})
        hard_raw = assertions_raw.get("hard", {})
        custom_raw = hard_raw.get("custom", [])

        custom_assertions = [
            CustomAssertion(
                type=c["type"],
                pattern=c.get("pattern", ""),
                scope=c.get("scope", "all_text"),
                check=c.get("check", ""),
                tool=c.get("tool", ""),
                tools=c.get("tools", []),
                count=c.get("count"),
                param_path=c.get("param_path", ""),
                expected=c.get("expected"),
            )
            for c in custom_raw
        ]

        follow_ups = [
            FollowUp(
                user_input=f["user_input"],
                fixtures_override=f.get("fixtures_override", {}),
            )
            for f in data.get("follow_ups", [])
        ]

        pre_state_raw = data.get("pre_state")
        pre_state = None
        if pre_state_raw and isinstance(pre_state_raw, dict):
            pre_state = PreState(
                session_id=pre_state_raw.get("session_id", ""),
                files=pre_state_raw.get("files", {}),
            )

        return cls(
            id=data["id"],
            name=data["name"],
            stage=data["stage"],
            priority=data["priority"],
            instruction=data["instruction"],
            fixtures=data.get("fixtures", {}),
            follow_ups=follow_ups,
            expected_behavior=data.get("expected_behavior", ""),
            assertions=Assertions(
                hard=HardAssertions(
                    rules=hard_raw.get("rules", []),
                    custom=custom_assertions,
                ),
                soft=assertions_raw.get("soft", "all"),
            ),
            pre_state=pre_state,
            runtime=data.get("runtime", "claude-code"),
            max_turns=data.get("max_turns", 100),
            timeout=data.get("timeout", 120),
        )


# --- Result Models ---


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    message: str = ""
    description: str = ""


@dataclass
class HardResult:
    results: list[RuleResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def all_pass(self) -> bool:
        return not self.skipped and all(r.passed for r in self.results)

    @classmethod
    def skip(cls, reason: str) -> HardResult:
        return cls(skipped=True, skip_reason=reason)


@dataclass
class SoftResult:
    """4-dimension soft scoring result from LLM judge."""
    conciseness: float = 0.0
    correctness: float = 0.0
    naturalness: float = 0.0
    ux: float = 0.0
    issues: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def weighted_score(self) -> float:
        return (
            self.conciseness * 0.30
            + self.correctness * 0.30
            + self.naturalness * 0.20
            + self.ux * 0.20
        )

    @classmethod
    def skip(cls, reason: str) -> "SoftResult":
        return cls(skipped=True, skip_reason=reason)


@dataclass
class RunResult:
    """Raw execution result from CLI driver (before validation)."""
    transcript_path: Optional[str] = None
    duration: float = 0.0
    raw_output: str = ""
    error: Optional[str] = None
    success: bool = True


@dataclass
class TestResult:
    """Validated result for a single test case execution."""
    case_id: str
    verdict: Verdict
    hard_result: HardResult = field(default_factory=HardResult)
    transcript_path: Optional[str] = None
    duration: float = 0.0
    error: Optional[str] = None
    soft_result: Optional[SoftResult] = None


@dataclass
class CaseVerdict:
    """Aggregated verdict across multiple repetitions of a case."""
    case_id: str
    priority: str
    verdict: Verdict
    trigger_rate: float = 1.0
    pass_rate: float = 1.0
    detail: str = ""
    runs: list[TestResult] = field(default_factory=list)
    avg_soft_score: Optional[float] = None
