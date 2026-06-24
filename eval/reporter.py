"""Report generator: terminal summary + Markdown detailed report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from eval.models import (
    HardResult,
    ParsedTranscript,
    SoftResult,
    TestCase,
    ToolCallEvent,
)


def print_verbose_summary(
    case: TestCase,
    transcript: Optional[ParsedTranscript],
    hard_result: HardResult,
    verdict: str,
    duration: float,
    error: Optional[str] = None,
    soft_result: Optional[SoftResult] = None,
) -> None:
    """Print box summary to terminal."""
    icon = "✅" if verdict == "PASS" else "❌" if verdict == "FAIL" else "⏭️"

    print()
    print(f"┌─ {icon} {case.id}  [{verdict}]  ({duration:.1f}s)")
    print(f"│")

    # Section 1: Case Design
    print(f"├─ 📌 用例设计")
    print(f"│  指令: \"{case.instruction}\"")
    if case.expected_behavior:
        first_line = case.expected_behavior.strip().split("\n")[0][:60]
        print(f"│  期望: {first_line}")
    if case.follow_ups:
        fups = ", ".join(f'"{f.user_input}"' for f in case.follow_ups)
        print(f"│  交互: {fups}")
    print(f"│")

    # Section 2: Claude Output (full text joined)
    print(f"├─ 📤 Claude 输出")
    if error:
        print(f"│  ⚠ 执行错误: {error}")
    elif transcript:
        all_text = transcript.all_text().strip()
        if all_text:
            lines = all_text.split("\n")
            for line in lines[:12]:
                print(f"│  {line}")
            if len(lines) > 12:
                print(f"│  ... (共 {len(lines)} 行，省略 {len(lines) - 12} 行)")
        else:
            print(f"│  (无文本输出)")
    else:
        print(f"│  (无 transcript)")
    print(f"│")

    # Section 3: Assertions
    assertion_prefix = "├─" if soft_result else "└─"
    print(f"{assertion_prefix} 📋 断言裁决")
    if hard_result.skipped:
        print(f"   ⏭️  SKIP — {hard_result.skip_reason}")
    else:
        for r in hard_result.results:
            ri = "✅" if r.passed else "❌"
            desc = r.description or r.rule_id
            if r.passed:
                print(f"   {ri} {r.rule_id}: {desc}")
            else:
                print(f"   {ri} {r.rule_id}: {r.message or desc}")

    # Section 4: Soft scoring (only when present)
    if soft_result:
        if soft_result.skipped:
            print(f"│")
            print(f"└─ 📊 软评分 (跳过: {soft_result.skip_reason})")
        else:
            print(f"│")
            print(f"└─ 📊 软评分")
            print(f"   简洁度: {soft_result.conciseness:.1f} | 正确性: {soft_result.correctness:.1f} | 自然度: {soft_result.naturalness:.1f} | 体验: {soft_result.ux:.1f}")
            print(f"   加权: {soft_result.weighted_score():.1f}")


def write_case_report(
    case: TestCase,
    transcript: Optional[ParsedTranscript],
    hard_result: HardResult,
    verdict: str,
    duration: float,
    report_dir: Path,
    model: str = "",
    error: Optional[str] = None,
    soft_result: Optional[SoftResult] = None,
) -> Path:
    """Write detailed Markdown report for a single case run."""
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{case.id}.md"
    lines: list[str] = []

    icon = "✅" if verdict == "PASS" else "❌" if verdict == "FAIL" else "⏭️"

    # Header: identity + summary
    lines.append(f"# {icon} {case.id}")
    lines.append("")
    lines.append(f"| 项目 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 用例名 | {case.name} |")
    lines.append(f"| 裁决 | **{verdict}** |")
    lines.append(f"| 模型 | `{model}` |")
    lines.append(f"| 耗时 | {duration:.1f}s |")
    lines.append(f"| 优先级 | {case.priority} |")
    lines.append(f"| 阶段 | {case.stage} |")
    lines.append("")

    if case.expected_behavior:
        first_line = case.expected_behavior.strip().split("\n")[0]
        lines.append(f"> **期望**: {first_line}")
        lines.append("")

    lines.append("---")
    lines.append("")

    sec = 1

    # Section: Assertions (most important — readers look here first)
    lines.append(f"## {sec}. 断言裁决")
    lines.append("")

    if hard_result.skipped:
        lines.append(f"**SKIP**: {hard_result.skip_reason}")
    else:
        total = len(hard_result.results)
        passed_count = sum(1 for r in hard_result.results if r.passed)
        failed_count = total - passed_count
        summary_parts = [f"共 {total} 条断言", f"✅ {passed_count} 通过"]
        if failed_count:
            summary_parts.append(f"❌ {failed_count} 失败")
        lines.append("，".join(summary_parts))
        lines.append("")

        lines.append("| # | 规则 | 描述 | 结果 | 详情 |")
        lines.append("|--:|------|------|:----:|------|")
        for i, r in enumerate(hard_result.results, 1):
            ri = "✅" if r.passed else "❌"
            desc = (r.description or r.rule_id).replace("|", "\\|")
            detail = (r.message or "").replace("|", "\\|")
            lines.append(f"| {i} | {r.rule_id} | {desc} | {ri} | {detail} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Section: Soft scoring (conditional)
    if soft_result and not soft_result.skipped:
        sec += 1
        lines.append(f"## {sec}. 软评分")
        lines.append("")
        lines.append("| 维度 | 分数 | 权重 |")
        lines.append("|------|:----:|:----:|")
        lines.append(f"| 简洁度 | {soft_result.conciseness:.1f} | 30% |")
        lines.append(f"| 流程正确性 | {soft_result.correctness:.1f} | 30% |")
        lines.append(f"| 交互自然度 | {soft_result.naturalness:.1f} | 20% |")
        lines.append(f"| 用户体验 | {soft_result.ux:.1f} | 20% |")
        lines.append(f"| **加权总分** | **{soft_result.weighted_score():.1f}** | |")
        lines.append("")
        if soft_result.issues:
            lines.append("**问题**: " + "；".join(soft_result.issues))
        else:
            lines.append("**问题**: (无)")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Section: Claude Output (what the user actually sees)
    sec += 1
    lines.append(f"## {sec}. Claude 输出")
    lines.append("")

    if error:
        lines.append(f"**执行错误**: {error}")
        lines.append("")
    elif transcript:
        _append_text_by_turn(lines, case, transcript)
    else:
        lines.append("(无 transcript)")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Section: Execution Trace (tool calls — for debugging)
    sec += 1
    lines.append(f"## {sec}. 执行轨迹")
    lines.append("")

    if transcript:
        actions = transcript.actions
        if actions:
            lines.append("| # | 工具 | 关键参数 |")
            lines.append("|--:|------|----------|")
            for i, action in enumerate(actions, 1):
                param_summary = _summarize_tool_params(action)
                lines.append(f"| {i} | `{action.tool}` | {param_summary} |")
            lines.append("")
    else:
        lines.append("(无 transcript)")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Section: Case Design (appendix — collapsible)
    sec += 1
    lines.append("<details>")
    lines.append(f"<summary><strong>{sec}. 用例设计（展开查看）</strong></summary>")
    lines.append("")
    lines.append(f"**指令**: `{case.instruction}`")
    lines.append("")
    if case.follow_ups:
        fups = ", ".join(f'`{f.user_input}`' for f in case.follow_ups)
        lines.append(f"**追问**: {fups}")
        lines.append("")
    if case.expected_behavior:
        lines.append("**预期行为**:")
        lines.append("")
        for bline in case.expected_behavior.strip().split("\n"):
            lines.append(f"> {bline}")
        lines.append("")
    if case.fixtures:
        lines.append("**Fixtures**:")
        lines.append("")
        for cmd, resp in case.fixtures.items():
            summary = json.dumps(resp, ensure_ascii=False)
            if len(summary) > 100:
                summary = summary[:97] + "..."
            lines.append(f"- `{cmd}`: `{summary}`")
        lines.append("")
    lines.append("</details>")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _summarize_tool_params(action: ToolCallEvent) -> str:
    """Extract key parameters for display."""
    tool = action.tool
    params = action.params

    if tool == "Skill":
        return f"skill: {params.get('skill', '?')}"
    elif tool == "Bash":
        cmd = params.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return f"`{cmd}`"
    elif tool == "Read":
        return _short_path(params.get("file_path", ""))
    elif tool in ("TodoWrite", "TaskCreate"):
        if tool == "TodoWrite":
            todos = params.get("todos", [])
            contents = [t.get("content", "") for t in todos[:4]]
            return ", ".join(contents)
        else:
            return f'"{params.get("subject", "")}"'
    elif tool == "TaskUpdate":
        return f"taskId: {params.get('taskId', '')}, status: {params.get('status', params.get('activeForm', ''))}"
    elif tool in ("Write", "Edit"):
        return _short_path(params.get("file_path", ""))
    else:
        summary = json.dumps(params, ensure_ascii=False)
        if len(summary) > 80:
            summary = summary[:77] + "..."
        return summary


def _short_path(path: str) -> str:
    """Shorten absolute workspace paths for readability."""
    if "/workspaces/" in path:
        parts = path.split("/workspaces/", 1)
        after = parts[1]
        # Remove the workspace name prefix (e.g., "init_02_has_history_no_intent_run0/")
        segments = after.split("/", 1)
        return segments[1] if len(segments) > 1 else after
    if len(path) > 60:
        return "..." + path[-57:]
    return path


def _append_text_by_turn(lines: list[str], case: TestCase, transcript: ParsedTranscript) -> None:
    """Append text outputs grouped by turn."""
    # Build turn labels
    turn_labels = [f"Turn 0 (指令: \"{case.instruction[:50]}{'...' if len(case.instruction) > 50 else ''}\")"]
    for i, fu in enumerate(case.follow_ups):
        turn_labels.append(f"Turn {i + 1} (follow_up: \"{fu.user_input}\")")

    # Get turn boundaries from transcript
    scope_start = transcript._skill_boundary
    boundaries = [max(0, b - scope_start) for b in transcript._turn_boundaries]
    scope = transcript.skill_scope
    scope_len = len(scope)

    for turn_idx, label in enumerate(turn_labels):
        start = boundaries[turn_idx] if turn_idx < len(boundaries) else scope_len
        end = boundaries[turn_idx + 1] if turn_idx + 1 < len(boundaries) else scope_len
        start = min(start, scope_len)
        end = min(end, scope_len)

        turn_texts = [
            e.text for e in scope[start:end]
            if hasattr(e, "text")
        ]
        combined = "\n".join(turn_texts).strip()

        if combined:
            lines.append(f"#### {label}")
            lines.append("")
            lines.append("```text")
            lines.append(combined)
            lines.append("```")
            lines.append("")

    # If only 1 turn and no follow_ups, show all text simply
    if not case.follow_ups:
        all_text = transcript.all_text().strip()
        if all_text and not any("```text" in l for l in lines[-20:]):
            lines.append("```text")
            lines.append(all_text)
            lines.append("```")
            lines.append("")
