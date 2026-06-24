"""Static validation for Skill documents (Layer 1).

Checks cross-references, terminology compliance, and structural completeness.
Zero-cost, runs in seconds.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from eval.validator.patterns import FORBIDDEN_TERMS, FIXED_TODOWRITE_CONTENTS

SKILL_ROOT = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "skill-evaluation"

# Directories that legitimately reference internal terms (instructions TO Claude)
TERM_CHECK_EXCLUDED_DIRS = {"references", "processes"}


@dataclass
class LintContext:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _strip_code_spans(line: str) -> str:
    """Remove inline backtick content from a line for term checking."""
    return re.sub(r"`[^`]+`", "", line)


def check_forbidden_terms(ctx: LintContext) -> None:
    """Scan user-facing Skill docs for forbidden terms.

    Excludes: references/, processes/ (instructional docs that define internal terms),
    fenced code blocks, and inline backtick spans.
    """
    for md_file in SKILL_ROOT.rglob("*.md"):
        rel = md_file.relative_to(SKILL_ROOT)
        top_dir = rel.parts[0] if len(rel.parts) > 1 else ""
        if top_dir in TERM_CHECK_EXCLUDED_DIRS:
            continue

        content = md_file.read_text(encoding="utf-8")
        in_code_block = False
        for line_no, line in enumerate(content.splitlines(), 1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            clean_line = _strip_code_spans(line)
            for term in FORBIDDEN_TERMS:
                if term in clean_line:
                    ctx.error(f"[术语合规] {rel}:{line_no} — 禁用术语 '{term}'")


def check_todowrite_content(ctx: LintContext) -> None:
    """Verify all TodoWrite examples use exactly the 4 fixed stage names."""
    pattern = re.compile(r'"content"\s*:\s*"([^"]+)"')
    for md_file in SKILL_ROOT.rglob("*.md"):
        rel = md_file.relative_to(SKILL_ROOT)
        content = md_file.read_text(encoding="utf-8")
        for match in pattern.findall(content):
            if match in FIXED_TODOWRITE_CONTENTS:
                continue
            if any(kw in match for kw in ("评测", "报告", "场景", "数据")):
                ctx.error(f"[TodoWrite] {rel} — 非法 content: '{match}'，必须是固定 4 阶段名之一")


def check_scene_name_consistency(ctx: LintContext) -> None:
    """Check that scene names in scene-detection.md match 评测场景说明.md."""
    scene_detection = SKILL_ROOT / "processes" / "scene-detection.md"
    scene_ref = SKILL_ROOT / "references" / "评测场景说明.md"

    if not scene_detection.is_file():
        ctx.warn("[场景一致性] processes/scene-detection.md 不存在")
        return
    if not scene_ref.is_file():
        ctx.warn("[场景一致性] references/评测场景说明.md 不存在")
        return

    ref_content = scene_ref.read_text(encoding="utf-8")
    detection_content = scene_detection.read_text(encoding="utf-8")

    ref_scenes: set[str] = set()
    for line in ref_content.splitlines():
        m = re.match(r"^##\s+(.+?)(?:\s*$)", line)
        if m and "场景" not in m.group(1) and "说明" not in m.group(1):
            ref_scenes.add(m.group(1).strip())

    for scene in ref_scenes:
        if scene not in detection_content:
            ctx.warn(f"[场景一致性] 场景 '{scene}' 在评测场景说明.md 中定义但未出现在 scene-detection.md")


def check_command_format(ctx: LintContext) -> None:
    """Verify subcommands referenced in stage docs are defined in 脚本定义.md."""
    script_def = SKILL_ROOT / "references" / "脚本定义.md"
    if not script_def.is_file():
        ctx.warn("[命令校验] references/脚本定义.md 不存在")
        return

    script_content = script_def.read_text(encoding="utf-8")

    defined_commands: set[str] = set()
    for line in script_content.splitlines():
        m = re.match(r"^#+\s+(\S+)\s*$", line)
        if m:
            defined_commands.add(m.group(1))
        for match in re.finditer(r"eval_skill\.py\s+(\S+)", line):
            defined_commands.add(match.group(1))

    if not defined_commands:
        return

    stage_docs = [
        SKILL_ROOT / "eval-init.md",
        SKILL_ROOT / "eval-build.md",
        SKILL_ROOT / "eval-set.md",
        SKILL_ROOT / "eval-execute.md",
    ]
    for doc in stage_docs:
        if not doc.is_file():
            continue
        content = doc.read_text(encoding="utf-8")
        rel = doc.relative_to(SKILL_ROOT)
        for m in re.finditer(r"eval_skill\.py\s+(\S+)", content):
            cmd = m.group(1)
            if cmd not in defined_commands:
                ctx.error(f"[命令校验] {rel} — 引用子命令 '{cmd}' 未在脚本定义.md 中定义")


def check_doc_references(ctx: LintContext) -> None:
    """Check that markdown link targets actually exist."""
    for md_file in SKILL_ROOT.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        rel = md_file.relative_to(SKILL_ROOT)

        for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", content):
            link_target = m.group(2)
            if link_target.startswith(("http", "#")):
                continue
            # Strip anchor fragments from path
            path_part = link_target.split("#")[0]
            if not path_part:
                continue
            target_path = (md_file.parent / path_part).resolve()
            if not target_path.exists():
                ctx.warn(f"[引用完整] {rel} — 链接目标不存在: {link_target}")


def main() -> int:
    if not SKILL_ROOT.is_dir():
        print(f"Skill 目录不存在: {SKILL_ROOT}")
        return 1

    ctx = LintContext()

    check_forbidden_terms(ctx)
    check_todowrite_content(ctx)
    check_scene_name_consistency(ctx)
    check_command_format(ctx)
    check_doc_references(ctx)

    md_count = sum(1 for _ in SKILL_ROOT.rglob("*.md"))
    print(f"Skill Lint — {SKILL_ROOT.name}")
    print(f"  Scanned: {md_count} markdown files")
    print()

    if ctx.errors:
        print(f"Errors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  ✗ {e}")
        print()

    if ctx.warnings:
        print(f"Warnings ({len(ctx.warnings)}):")
        for w in ctx.warnings:
            print(f"  ⚠ {w}")
        print()

    if ctx.passed and not ctx.warnings:
        print("  ✅ All checks passed.")

    if not ctx.passed:
        print(f"Result: FAIL ({len(ctx.errors)} errors, {len(ctx.warnings)} warnings)")
        return 1

    print(f"Result: PASS ({len(ctx.warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
