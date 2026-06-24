"""Workspace builder: creates isolated test environments."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from eval.models import PreState, TestCase


class WorkspaceBuilder:
    """Creates isolated workspace directories for each test run."""

    def __init__(self, skill_source: Path, mock_script: Path):
        self.skill_source = skill_source
        self.mock_script = mock_script

    def build(self, case: TestCase, base_dir: Path, run_index: int = 0) -> Path:
        workspace = base_dir / f"{case.id}_run{run_index}"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)

        self._copy_skill_docs(workspace)
        self._install_mock_script(workspace)
        self._write_fixtures(workspace, case.fixtures)
        self._create_eval_dir(workspace)
        if case.pre_state:
            self._seed_pre_state(workspace, case.pre_state)
        self._write_claude_md(workspace, case.pre_state)

        return workspace

    def _copy_skill_docs(self, workspace: Path) -> None:
        dest = workspace / ".claude" / "skills" / "skill-evaluation"
        shutil.copytree(
            self.skill_source,
            dest,
            ignore=shutil.ignore_patterns("scripts", "__pycache__", "*.pyc", "eval_skill.py"),
        )

    def _install_mock_script(self, workspace: Path) -> None:
        dest = workspace / ".claude" / "skills" / "skill-evaluation" / "eval_skill.py"
        shutil.copy2(self.mock_script, dest)
        os.chmod(dest, 0o755)

    def _write_fixtures(self, workspace: Path, fixtures: dict) -> None:
        fixtures_dir = workspace / ".eval-fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        for cmd, response in fixtures.items():
            fixture_path = fixtures_dir / f"{cmd}.json"
            fixture_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _create_eval_dir(self, workspace: Path) -> None:
        (workspace / ".eval").mkdir(exist_ok=True)

    _CROSS_SESSION_FILES = {"auth.json", "custom-models.json", "tasks.json", "eval-models-cache.json"}

    def _seed_pre_state(self, workspace: Path, pre_state: PreState) -> None:
        eval_dir = workspace / ".eval"
        session_dir = eval_dir / pre_state.session_id if pre_state.session_id else None
        if session_dir:
            session_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in pre_state.files.items():
            if filename in self._CROSS_SESSION_FILES:
                target = eval_dir / filename
            elif session_dir:
                target = session_dir / filename
            else:
                target = eval_dir / filename
            target.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # --- Resume Directive (CLAUDE.md generation) ---

    _STAGE_NAMES = {
        "build": "配置评测对象",
        "set": "准备评测数据",
        "execute": "提交并查看报告",
    }

    _STAGE_DOCS = {
        "build": "eval-build.md",
        "set": "eval-set.md",
        "execute": "eval-execute.md",
    }

    def _determine_target_stage(self, pre_state: PreState) -> str:
        files = set(pre_state.files.keys())
        has_build = {"eval-runtimes.json", "eval-models.json", "eval-judge.json"}.issubset(files)
        has_set = has_build and "eval-dataset-meta.json" in files
        if has_set:
            return "execute"
        if has_build:
            return "set"
        return "build"

    def _write_claude_md(self, workspace: Path, pre_state: PreState | None) -> None:
        script_path = workspace / ".claude" / "skills" / "skill-evaluation" / "eval_skill.py"
        script_override = self._format_script_override(str(script_path))

        if pre_state and pre_state.session_id:
            resume_directive = self._build_resume_directive(workspace, pre_state)
            content = f"{script_override}\n{resume_directive}"
        else:
            content = script_override

        (workspace / "CLAUDE.md").write_text(content, encoding="utf-8")

    def _format_script_override(self, script_path: str) -> str:
        return "\n".join([
            "# 脚本路径覆盖（强制）",
            "",
            "本工作区使用独立的 eval_skill.py 脚本。执行任何 eval_skill.py 命令时，"
            "必须使用以下绝对路径，禁止使用 Skill 文档中的 `{skill-dir}` 变量：",
            "",
            f"```",
            f"{script_path}",
            f"```",
            "",
            "示例：`python3 \"{script_path}\" check-token --auth-file ...`".replace("{script_path}", script_path),
            "",
        ])

    def _build_resume_directive(self, workspace: Path, pre_state: PreState) -> str:
        target = self._determine_target_stage(pre_state)
        parts = pre_state.session_id.split("_", 2)
        skill_name = parts[2] if len(parts) > 2 else "unknown"
        session_id = pre_state.session_id

        completed = []
        if target in ("set", "execute"):
            completed.append("初始化（确认评测场景）")
            completed.append("配置评测对象")
        if target == "execute":
            completed.append("准备评测数据")

        zip_url = ""
        fixtures_dir = workspace / ".eval-fixtures"
        package_fixture = fixtures_dir / "package.json"
        if package_fixture.exists():
            data = json.loads(package_fixture.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                zip_url = data.get("skill_zip_url", "")

        return self._format_resume_directive(
            session_id=session_id,
            skill_name=skill_name,
            target_stage_name=self._STAGE_NAMES[target],
            target_stage_doc=self._STAGE_DOCS[target],
            completed_stages=completed,
            zip_url=zip_url,
        )

    def _format_resume_directive(
        self,
        session_id: str,
        skill_name: str,
        target_stage_name: str,
        target_stage_doc: str,
        completed_stages: list[str],
        zip_url: str,
    ) -> str:
        lines = [
            "# 评测会话恢复指令",
            "",
            "本工作区存在已配置完成的评测会话。skill-evaluation 技能加载后，必须按以下指令执行。",
            "",
            "## 会话状态",
            "",
            f"- 会话 ID: `{session_id}`",
            f"- Skill 名称: `{skill_name}`",
            f"- 评测场景: 快速测试单个 Skill",
        ]
        if zip_url:
            lines.append(f"- Skill zip URL: `{zip_url}`")
        lines += [
            "",
            "## 已完成阶段",
            "",
        ]
        for s in completed_stages:
            lines.append(f"- ✅ {s}")
        lines += [
            "",
            f"## 当前阶段：{target_stage_name}",
            "",
            "## 执行要求（强制）",
            "",
            "1. 调用 TodoWrite 初始化 4 阶段进度（已完成阶段标记 completed，当前阶段标记 in_progress）",
            "2. 静默执行 check-token 验证 Token 有效性",
            f"3. **跳过所有已完成阶段**，不执行其中任何任务或用户交互",
            f"4. 读取阶段文档 `{target_stage_doc}`，按其中定义的任务列表执行",
            f"5. 会话目录: `.eval/{session_id}/`，所有中间文件读写使用此路径",
            "",
            "## 禁止事项",
            "",
            "- 禁止执行场景选择、Skill 搜索确认、模型选择等已完成阶段的交互",
            "- 禁止输出任何关于「恢复」「跳过」「检测到已有会话」的说明文字",
            "- 禁止重新询问已确定的配置（Skill、模型、运行框架）",
        ]
        return "\n".join(lines) + "\n"
