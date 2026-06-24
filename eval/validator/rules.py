"""Hard constraint validator with two-phase verdict."""
from __future__ import annotations

import re

from eval.models import (
    HardResult,
    ParsedTranscript,
    RuleResult,
    TestCase,
)
from eval.validator.assertions import run_custom_assertion
from eval.validator.patterns import (
    FIXED_TODOWRITE_CONTENTS,
    FORBIDDEN_PATTERNS,
    FORBIDDEN_TERMS_CONTEXTUAL,
    FORBIDDEN_TERMS_EXACT,
)


class HardConstraintValidator:
    """Two-phase rule validator.

    Phase 0: Check Skill loaded (H0) -> SKIP if not
    Phase 1: Universal rules (H1-H6) + Conditional rules (H7-H9) + Custom
    """

    def check(self, transcript: ParsedTranscript, case: TestCase) -> HardResult:
        # Phase 0: Skill loaded?
        if not transcript.skill_loaded:
            return HardResult.skip("Skill 未被触发加载")

        # Phase 1: Behavior rules within skill_scope
        results: list[RuleResult] = []

        # Universal rules (auto-execute)
        results.append(self._h1_first_action_todowrite(transcript))
        results.append(self._h2_no_text_before_todowrite(transcript))
        results.append(self._h3_todowrite_content_fixed(transcript))
        results.append(self._h4_no_forbidden_terms(transcript))
        results.append(self._h5_no_process_disclosure(transcript))
        results.append(self._h6_no_ask_user_question(transcript))

        # Conditional rules (per case)
        for rule_id in case.assertions.hard.rules:
            method_name = self._CONDITIONAL_RULE_METHODS.get(rule_id)
            if method_name:
                results.append(getattr(self, method_name)(transcript))

        # Custom assertions
        for custom in case.assertions.hard.custom:
            results.append(run_custom_assertion(custom, transcript))

        for r in results:
            if not r.description and r.rule_id in _DESCRIPTIONS:
                r.description = _DESCRIPTIONS[r.rule_id]

        return HardResult(results=results)

    # --- Universal Rules (H1-H6) ---

    _PROGRESS_TOOLS = {"TodoWrite", "TaskCreate"}

    def _h1_first_action_todowrite(self, transcript: ParsedTranscript) -> RuleResult:
        actions = transcript.actions
        if not actions:
            return RuleResult(rule_id="H1", passed=False, message="Skill 作用域内无任何工具调用")
        if actions[0].tool in self._PROGRESS_TOOLS:
            return RuleResult(rule_id="H1", passed=True)
        return RuleResult(
            rule_id="H1",
            passed=False,
            message=f"首动作应为 TodoWrite/TaskCreate，实际为 {actions[0].tool}",
        )

    def _h2_no_text_before_todowrite(self, transcript: ParsedTranscript) -> RuleResult:
        text_todo = transcript.text_before_tool("TodoWrite")
        text_task = transcript.text_before_tool("TaskCreate")
        if text_todo.strip() == "" or text_task.strip() == "":
            return RuleResult(rule_id="H2", passed=True)
        text_before = text_task if len(text_task) <= len(text_todo) else text_todo
        return RuleResult(
            rule_id="H2",
            passed=False,
            message=f"进度工具前有文本输出: {text_before[:80]}",
        )

    def _h3_todowrite_content_fixed(self, transcript: ParsedTranscript) -> RuleResult:
        call = transcript.first_tool_call("TodoWrite")
        if call:
            todos = call.params.get("todos", [])
            contents = [item.get("content", "") for item in todos]
            if contents == FIXED_TODOWRITE_CONTENTS:
                return RuleResult(rule_id="H3", passed=True)
            return RuleResult(
                rule_id="H3", passed=False,
                message=f"TodoWrite content 不匹配: {contents}",
            )
        task_calls = [e for e in transcript.actions if e.tool == "TaskCreate"]
        if not task_calls:
            return RuleResult(rule_id="H3", passed=False, message="未找到 TodoWrite/TaskCreate 调用")
        subjects = [c.params.get("subject", "") for c in task_calls]
        if sorted(subjects) == sorted(FIXED_TODOWRITE_CONTENTS):
            return RuleResult(rule_id="H3", passed=True)
        return RuleResult(
            rule_id="H3", passed=False,
            message=f"TaskCreate subjects 不匹配: {subjects}",
        )

    def _h4_no_forbidden_terms(self, transcript: ParsedTranscript) -> RuleResult:
        text = transcript.all_text()
        for term in FORBIDDEN_TERMS_EXACT:
            if term in text:
                return RuleResult(rule_id="H4", passed=False, message=f"术语泄露: {term}")
        for pattern in FORBIDDEN_TERMS_CONTEXTUAL:
            match = pattern.search(text)
            if match:
                return RuleResult(rule_id="H4", passed=False, message=f"术语泄露: {match.group()}")
        return RuleResult(rule_id="H4", passed=True)

    def _h5_no_process_disclosure(self, transcript: ParsedTranscript) -> RuleResult:
        text = transcript.all_text()
        for pattern in FORBIDDEN_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return RuleResult(
                    rule_id="H5",
                    passed=False,
                    message=f"过程泄露: {match.group()}",
                )
        return RuleResult(rule_id="H5", passed=True)

    def _h6_no_ask_user_question(self, transcript: ParsedTranscript) -> RuleResult:
        if not transcript.has_tool_call("AskUserQuestion"):
            return RuleResult(rule_id="H6", passed=True)
        return RuleResult(rule_id="H6", passed=False, message="禁止使用 AskUserQuestion")

    # --- Conditional Rules (H7-H9) ---

    def _h7_options_use_table(self, transcript: ParsedTranscript) -> RuleResult:
        text = transcript.all_text()
        numbered_list = re.findall(r"^\d+[\.\)]\s+\S+", text, re.MULTILINE)
        if len(numbered_list) >= 3:
            has_table = bool(re.search(r"\|.+\|.*\n\s*\|[-:\s|]+\|", text))
            if not has_table:
                return RuleResult(
                    rule_id="H7",
                    passed=False,
                    message="选项使用了编号列表而非 Markdown 表格",
                )
        return RuleResult(rule_id="H7", passed=True)

    def _h8_no_recommend_in_driver_models(self, transcript: ParsedTranscript) -> RuleResult:
        text = transcript.all_text()
        if "驱动模型" in text or "选择模型" in text:
            if "推荐" in text or "（推荐）" in text:
                return RuleResult(
                    rule_id="H8",
                    passed=False,
                    message="驱动模型列表不应标注推荐",
                )
        return RuleResult(rule_id="H8", passed=True)

    def _h9_guide_uses_placeholder(self, transcript: ParsedTranscript) -> RuleResult:
        text = transcript.all_text()
        if "请描述你的评测需求" in text:
            if "xxx skill" not in text.lower():
                return RuleResult(
                    rule_id="H9",
                    passed=False,
                    message="自然语言引导未使用 xxx Skill 占位符",
                )
        return RuleResult(rule_id="H9", passed=True)

    _CONDITIONAL_RULE_METHODS: dict[str, str] = {
        "H7": "_h7_options_use_table",
        "H8": "_h8_no_recommend_in_driver_models",
        "H9": "_h9_guide_uses_placeholder",
    }


_DESCRIPTIONS: dict[str, str] = {
    "H1": "首个动作是进度管理工具",
    "H2": "进度工具之前无文本输出",
    "H3": "进度内容为4个固定阶段名",
    "H4": "无禁用术语泄露",
    "H5": "无内部ID/字段泄露",
    "H6": "禁止使用 AskUserQuestion",
    "H7": "选项使用Markdown表格",
    "H8": "驱动模型不标注推荐",
    "H9": "引导含 xxx Skill 占位符",
}
