"""4-dimension soft scoring LLM judge."""
from __future__ import annotations

import json
import os
import sys

from eval.models import SoftResult, TestCase

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "claude-sonnet-4-6")

_SYSTEM = """你是评测质量评分器。根据用例的预期行为，对 Claude 的实际输出在 4 个维度上打分（1-5）。

## 评分维度

### 简洁度 (conciseness) — 权重 30%
- 5: 零冗余，每句话都有信息增量
- 4: 偶有冗余但不影响阅读
- 3: 有明显重复或不必要的解释
- 2: 大段无关内容
- 1: 输出混乱，充斥无用信息

### 流程正确性 (correctness) — 权重 30%
- 5: 完全按照预期流程执行，无遗漏无多余
- 4: 流程正确，有微小偏差但不影响结果
- 3: 关键步骤正确但顺序或细节有误
- 2: 遗漏关键步骤或执行了错误操作
- 1: 完全偏离预期流程

### 交互自然度 (naturalness) — 权重 20%
- 5: 中文流畅自然，像人类助手在交流
- 4: 表达通顺，偶有生硬
- 3: 可读但有明显机器感
- 2: 措辞怪异或混合语言
- 1: 难以理解

### 用户体验 (ux) — 权重 20%
- 5: 信息层次清晰，操作引导明确，用户零困惑
- 4: 整体体验好，有小瑕疵
- 3: 能用但体验平庸
- 2: 用户需要猜测含义或操作
- 1: 体验混乱

## 输出格式

严格输出 JSON，不要输出其他内容：
{"conciseness": X, "correctness": X, "naturalness": X, "ux": X, "issues": ["问题1", "问题2"]}

issues 列出扣分原因（0-3 条），无问题时为空数组。"""

_PROMPT = """评分任务：

**用例名称**: {case_name}
**预期行为**: {expected_behavior}

**Claude 实际输出**:
---
{text}
---

请对以上输出在 4 个维度上打 1-5 分。"""


def judge_soft(case: TestCase, text: str) -> SoftResult:
    if os.environ.get("EVAL_SOFT_ENABLED") == "0":
        return SoftResult.skip("EVAL_SOFT_ENABLED=0")

    if case.assertions.soft == "none":
        return SoftResult.skip("soft=none")

    try:
        import anthropic

        client = anthropic.Anthropic()
        prompt = _PROMPT.format(
            case_name=case.name,
            expected_behavior=case.expected_behavior or "(无明确预期)",
            text=text[:3000],
        )
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=200,
            temperature=0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        return SoftResult(
            conciseness=float(result.get("conciseness", 0)),
            correctness=float(result.get("correctness", 0)),
            naturalness=float(result.get("naturalness", 0)),
            ux=float(result.get("ux", 0)),
            issues=result.get("issues", []),
        )
    except Exception as e:
        print(f"  ⚠ Soft judge error: {e}", file=sys.stderr)
        return SoftResult.skip(str(e))
