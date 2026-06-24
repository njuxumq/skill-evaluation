"""Skill test driver: executes Claude Code CLI and collects results."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from eval.models import FollowUp, RunResult, TestCase
from eval.runner.workspace import WorkspaceBuilder


class SkillTestDriver:
    """Drives Claude Code CLI for skill behavior testing."""

    ALLOWED_TOOLS = "Read,Edit,Write,Bash,Glob,Grep,Agent,Skill,TodoWrite,TaskCreate,TaskUpdate"

    def __init__(
        self,
        skill_source: Path,
        work_dir: Path,
        model_settings: Optional[Path] = None,
        max_turns: int = 100,
        timeout: int = 120,
    ):
        self.mock_script = Path(__file__).resolve().parent.parent / "mock_eval_skill.py"
        self.workspace_builder = WorkspaceBuilder(skill_source, self.mock_script)
        self.work_dir = work_dir
        self.model_settings = model_settings
        self.max_turns = max_turns
        self.timeout = timeout

    async def run_case(self, case: TestCase, run_index: int = 0) -> RunResult:
        workspace = self.workspace_builder.build(case, self.work_dir, run_index)
        effective_timeout = case.timeout or self.timeout
        effective_max_turns = case.max_turns or self.max_turns
        try:
            session_id, transcript_path, duration = await self._execute_turn(
                workspace, case.instruction, session_id=None,
                timeout=effective_timeout, max_turns=effective_max_turns,
            )

            for follow_up in case.follow_ups:
                if follow_up.fixtures_override:
                    self._update_fixtures(workspace, follow_up.fixtures_override)
                session_id, new_transcript, extra_dur = await self._execute_turn(
                    workspace, follow_up.user_input, session_id=session_id,
                    timeout=effective_timeout, max_turns=effective_max_turns,
                )
                if new_transcript:
                    transcript_path = new_transcript
                duration += extra_dur

            return RunResult(
                transcript_path=transcript_path,
                duration=duration,
                success=True,
            )
        except asyncio.TimeoutError:
            return RunResult(error="Execution timed out", success=False)
        except Exception as e:
            return RunResult(error=str(e), success=False)

    async def _execute_turn(
        self,
        workspace: Path,
        instruction: str,
        session_id: Optional[str],
        timeout: int,
        max_turns: int = 100,
    ) -> tuple[Optional[str], Optional[str], float]:
        cmd = self._build_command(instruction, session_id, max_turns)
        env = self._build_env()
        start_wall = time.time()
        start_mono = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        duration = time.monotonic() - start_mono

        # Small delay to ensure transcript is flushed
        await asyncio.sleep(0.3)

        transcript_path, new_session_id = self._collect_transcript(workspace, start_wall)
        return new_session_id or session_id, transcript_path, duration

    def _build_command(self, instruction: str, session_id: Optional[str] = None, max_turns: int = 100) -> list[str]:
        claude_bin = shutil.which("claude") or "claude"
        cmd = [
            claude_bin,
            "-p", instruction,
            "--output-format", "json",
            "--max-turns", str(max_turns),
            "--allowedTools", self.ALLOWED_TOOLS,
        ]
        if self.model_settings:
            cmd.extend(["--settings", str(self.model_settings)])
        if session_id:
            cmd.extend(["--resume", session_id])
        return cmd

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["ECC_GATEGUARD"] = "off"
        return env

    def _collect_transcript(
        self, workspace: Path, start_wall_time: float
    ) -> tuple[Optional[str], Optional[str]]:
        """Find transcript JSONL produced by this run. Returns (path, session_id)."""
        projects_dir = Path.home() / ".claude" / "projects"
        if not projects_dir.is_dir():
            return None, None

        project_dir = None
        for candidate in self._encoded_workspace_candidates(workspace):
            current = projects_dir / candidate
            if current.is_dir():
                project_dir = current
                break

        if project_dir is None:
            return None, None

        candidates: list[tuple[float, Path]] = []
        for f in project_dir.iterdir():
            if f.suffix == ".jsonl" and f.is_file():
                mtime = f.stat().st_mtime
                if mtime >= start_wall_time - 1.0:
                    candidates.append((mtime, f))

        if not candidates:
            return None, None

        candidates.sort(key=lambda pair: pair[0])
        _, src = candidates[-1]

        dest = workspace / "transcript.jsonl"
        shutil.copy2(src, dest)
        session_id = src.stem
        return str(dest), session_id

    def _encoded_workspace_candidates(self, workspace: Path) -> list[str]:
        resolved = workspace.resolve()
        raw = str(resolved)
        normalized = re.sub(r"[/_.]", "-", raw)
        return [
            normalized,
            raw.replace("/", "-").replace("_", "-"),
            raw.replace("/", "-"),
        ]

    def _update_fixtures(self, workspace: Path, overrides: dict) -> None:
        fixtures_dir = workspace / ".eval-fixtures"
        for cmd, response in overrides.items():
            fixture_path = fixtures_dir / f"{cmd}.json"
            fixture_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
