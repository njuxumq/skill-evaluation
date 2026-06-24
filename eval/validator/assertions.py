"""Custom assertion type implementations."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eval.models import ParsedTranscript

from eval.models import CustomAssertion, RuleResult

_TOOL_ALIASES = {
    "TodoWrite": {"TodoWrite", "TaskCreate"},
}


def _matches_tool(actual: str, expected: str) -> bool:
    aliases = _TOOL_ALIASES.get(expected)
    if aliases:
        return actual in aliases
    return actual == expected


def _make_description(assertion: CustomAssertion) -> str:
    t = assertion.type
    p = assertion.pattern or ""
    if t == "text_present":
        return f"输出含 \"{p[:30]}\""
    if t == "text_absent":
        return f"输出不含 \"{p[:30]}\""
    if t == "regex_match":
        return f"匹配 /{p[:25]}/"
    if t == "regex_absent":
        return f"不匹配 /{p[:25]}/"
    if t == "tool_called":
        return f"调用了 {assertion.tool}"
    if t == "tool_not_called":
        return f"未调用 {assertion.tool}"
    if t == "format_check":
        return f"格式: {assertion.check}"
    if t == "tool_order":
        return f"调用顺序: {','.join(assertion.tools or [])}"
    if t == "tool_param_check":
        return f"参数检查: {assertion.tool}.{assertion.param_path}"
    if t == "semantic_match":
        return f"🤖 语义含 \"{p[:30]}\""
    if t == "semantic_absent":
        return f"🤖 语义不含 \"{p[:30]}\""
    return t


def run_custom_assertion(assertion: CustomAssertion, transcript: "ParsedTranscript") -> RuleResult:
    """Dispatch, execute, and attach description."""
    result = _evaluate_assertion(assertion, transcript)
    result.description = _make_description(assertion)
    return result


def _evaluate_assertion(assertion: CustomAssertion, transcript: "ParsedTranscript") -> RuleResult:
    """Dispatch and execute a single custom assertion."""
    atype = assertion.type

    if atype in ("text_present", "text_absent", "regex_match", "regex_absent"):
        text = _resolve_scope(assertion.scope, transcript)
        if atype == "text_present":
            return _check_text_present(text, assertion.pattern)
        elif atype == "text_absent":
            return _check_text_absent(text, assertion.pattern)
        elif atype == "regex_match":
            return _check_regex_match(text, assertion.pattern)
        elif atype == "regex_absent":
            return _check_regex_absent(text, assertion.pattern)

    elif atype in ("semantic_match", "semantic_absent"):
        text = _resolve_scope(assertion.scope, transcript)
        from eval.validator.llm_judge import judge_semantic
        return judge_semantic(atype, text, assertion.pattern)

    elif atype == "format_check":
        text = _resolve_scope(assertion.scope, transcript)
        return _check_format(text, assertion.check)

    elif atype == "tool_called":
        return _check_tool_called(transcript, assertion.tool, assertion.count)

    elif atype == "tool_not_called":
        return _check_tool_not_called(transcript, assertion.tool)

    elif atype == "tool_order":
        return _check_tool_order(transcript, assertion.tools)

    elif atype == "tool_param_check":
        return _check_tool_param(transcript, assertion.tool, assertion.param_path, assertion.expected)

    return RuleResult(rule_id=f"custom:{atype}", passed=False, message=f"Unknown assertion type: {atype}")


def _resolve_scope(scope: str, transcript: "ParsedTranscript") -> str:
    if scope == "first_text_output":
        return transcript.first_text_output()
    elif scope == "all_text":
        return transcript.all_text()
    elif scope == "last_text_output":
        return transcript.last_text_output()
    elif scope.startswith("turn_"):
        try:
            n = int(scope.split("_", 1)[1])
            return transcript.turn_text(n)
        except (ValueError, IndexError):
            return ""
    return transcript.all_text()


def _check_text_present(text: str, pattern: str) -> RuleResult:
    if pattern in text:
        return RuleResult(rule_id="text_present", passed=True)
    return RuleResult(
        rule_id="text_present",
        passed=False,
        message=f"Expected text not found: '{pattern}'",
    )


def _check_text_absent(text: str, pattern: str) -> RuleResult:
    if pattern not in text:
        return RuleResult(rule_id="text_absent", passed=True)
    return RuleResult(
        rule_id="text_absent",
        passed=False,
        message=f"Forbidden text found: '{pattern}'",
    )


def _check_regex_match(text: str, pattern: str) -> RuleResult:
    if re.search(pattern, text):
        return RuleResult(rule_id="regex_match", passed=True)
    return RuleResult(
        rule_id="regex_match",
        passed=False,
        message=f"Pattern not matched: '{pattern}'",
    )


def _check_regex_absent(text: str, pattern: str) -> RuleResult:
    match = re.search(pattern, text)
    if not match:
        return RuleResult(rule_id="regex_absent", passed=True)
    return RuleResult(
        rule_id="regex_absent",
        passed=False,
        message=f"Forbidden pattern matched: '{match.group()}'",
    )


def _check_format(text: str, check: str) -> RuleResult:
    if check == "markdown_table":
        if "|" in text and "---" in text:
            return RuleResult(rule_id="format_check:markdown_table", passed=True)
        return RuleResult(
            rule_id="format_check:markdown_table",
            passed=False,
            message="Expected markdown table not found",
        )
    elif check == "numbered_list":
        if re.search(r"^\d+[\.\)]\s+\S+", text, re.MULTILINE):
            return RuleResult(rule_id="format_check:numbered_list", passed=True)
        return RuleResult(
            rule_id="format_check:numbered_list",
            passed=False,
            message="Expected numbered list not found",
        )
    return RuleResult(rule_id=f"format_check:{check}", passed=False, message=f"Unknown check: {check}")


def _check_tool_called(transcript: "ParsedTranscript", tool: str, count: int | None) -> RuleResult:
    actual = sum(1 for e in transcript.actions if _matches_tool(e.tool, tool))
    if count is not None:
        if actual == count:
            return RuleResult(rule_id=f"tool_called:{tool}", passed=True)
        return RuleResult(
            rule_id=f"tool_called:{tool}",
            passed=False,
            message=f"Expected {tool} called {count} times, got {actual}",
        )
    if actual > 0:
        return RuleResult(rule_id=f"tool_called:{tool}", passed=True)
    return RuleResult(
        rule_id=f"tool_called:{tool}",
        passed=False,
        message=f"Expected {tool} to be called, but it was not",
    )


def _check_tool_not_called(transcript: "ParsedTranscript", tool: str) -> RuleResult:
    if not transcript.has_tool_call(tool):
        return RuleResult(rule_id=f"tool_not_called:{tool}", passed=True)
    return RuleResult(
        rule_id=f"tool_not_called:{tool}",
        passed=False,
        message=f"Tool {tool} should not be called but was",
    )


def _check_tool_order(transcript: "ParsedTranscript", tools: list[str]) -> RuleResult:
    actual_tools = [e.tool for e in transcript.actions]
    idx = 0
    for tool in tools:
        found = False
        while idx < len(actual_tools):
            if _matches_tool(actual_tools[idx], tool):
                found = True
                idx += 1
                break
            idx += 1
        if not found:
            return RuleResult(
                rule_id="tool_order",
                passed=False,
                message=f"Expected tool order {tools}, but {tool} not found in sequence",
            )
    return RuleResult(rule_id="tool_order", passed=True)


_MISSING = object()


def _check_tool_param(
    transcript: "ParsedTranscript", tool: str, param_path: str, expected: object
) -> RuleResult:
    call = next((e for e in transcript.actions if _matches_tool(e.tool, tool)), None)
    if not call:
        return RuleResult(
            rule_id=f"tool_param:{tool}",
            passed=False,
            message=f"Tool {tool} not called",
        )
    value: object = call.params
    for key in param_path.split("."):
        if isinstance(value, dict):
            value = value.get(key, _MISSING)
        elif isinstance(value, list):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                value = _MISSING
        else:
            value = _MISSING
        if value is _MISSING:
            return RuleResult(
                rule_id=f"tool_param:{tool}.{param_path}",
                passed=False,
                message=f"Path '{param_path}' not found in {tool} params",
            )

    if value == expected:
        return RuleResult(rule_id=f"tool_param:{tool}.{param_path}", passed=True)
    return RuleResult(
        rule_id=f"tool_param:{tool}.{param_path}",
        passed=False,
        message=f"Expected {expected}, got {value}",
    )
