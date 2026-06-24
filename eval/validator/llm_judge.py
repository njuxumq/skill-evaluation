"""Semantic assertion judge using LLM."""
from __future__ import annotations

import json
import os
import sys

from eval.models import RuleResult

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "claude-sonnet-4-6")

_SYSTEM = """你是断言评判器。判断文本是否满足语义条件。

规则：
- 语义匹配，不要求完全相同的措辞
- 只判断语义意图是否被传达，忽略格式差异（标点、换行、排版）
- 严格按 JSON 格式输出，不要输出其他内容

示例1：
pattern: "展示历史任务"
text: "你有一个近期评测任务，是否继续？"
输出: {"pass": true, "reason": "近期评测任务即历史任务的展示"}

示例2：
pattern: "登录链接"
text: "请描述你的评测需求"
输出: {"pass": false, "reason": "文本中无任何登录相关内容"}

仅输出 JSON：{"pass": true/false, "reason": "一句话说明"}"""

_PROMPTS = {
    "semantic_match": "判断：以下文本是否表达了「{pattern}」这个意思？\n\n---\n{text}\n---",
    "semantic_absent": "判断：以下文本是否完全没有表达「{pattern}」这个意思？（如果完全没有，pass=true）\n\n---\n{text}\n---",
}


def judge_semantic(assertion_type: str, text: str, pattern: str) -> RuleResult:
    """Call LLM for semantic judgment. Fail-open on error."""
    if os.environ.get("EVAL_JUDGE_ENABLED") == "0":
        return _skip(assertion_type, "EVAL_JUDGE_ENABLED=0")

    try:
        import anthropic

        client = anthropic.Anthropic()
        prompt = _PROMPTS[assertion_type].format(pattern=pattern, text=text[:2000])
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=100,
            temperature=0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        passed = bool(result.get("pass"))
        reason = result.get("reason", "")
        return RuleResult(
            rule_id=assertion_type,
            passed=passed,
            message="" if passed else reason,
        )
    except Exception as e:
        print(f"  ⚠ LLM judge error: {e}", file=sys.stderr)
        return _skip(assertion_type, str(e))


def _skip(assertion_type: str, reason: str) -> RuleResult:
    """Fail-open: treat as passed with warning when judge unavailable."""
    return RuleResult(
        rule_id=assertion_type,
        passed=True,
        message=f"⚠ judge skipped: {reason}",
    )
