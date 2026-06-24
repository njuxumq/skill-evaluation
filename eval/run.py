"""Skill evaluation harness CLI entry point.

Orchestrates: load cases → drive CLI → parse transcript → validate → aggregate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from eval.models import (
    CaseVerdict,
    TestCase,
    TestResult,
    Verdict,
)
from eval.reporter import print_verbose_summary, write_case_report
from eval.runner.driver import SkillTestDriver
from eval.runner.transcript import TranscriptParser
from eval.validator.rules import HardConstraintValidator

VERSION = "0.1.0"

MODELS_DIR = Path(__file__).resolve().parent / "models"
SKILL_SOURCE = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "skill-evaluation"


def _read_global_model_name() -> str:
    """Read model name from user's global ~/.claude/settings.json."""
    global_settings = Path.home() / ".claude" / "settings.json"
    if not global_settings.is_file():
        return "(global default)"
    try:
        data = json.loads(global_settings.read_text(encoding="utf-8"))
        return data.get("model", "") or data.get("env", {}).get("ANTHROPIC_MODEL", "(global default)")
    except (json.JSONDecodeError, OSError):
        return "(global default)"


def resolve_model_settings(model_name: Optional[str]) -> tuple[str, Optional[Path]]:
    """Resolve --model arg to (display_name, settings_path).

    If model_name is None, uses user's global claude config.
    """
    if not model_name:
        display = _read_global_model_name()
        return display, None

    settings_path = MODELS_DIR / f"{model_name}.json"
    if not settings_path.is_file():
        settings_path = Path(model_name)
        if not settings_path.is_file():
            print(f"Error: Model config not found: {model_name}")
            print(f"  Looked in: {MODELS_DIR / f'{model_name}.json'}")
            print(f"  Available: {', '.join(p.stem for p in MODELS_DIR.glob('*.json') if p.stem != 'example')}")
            sys.exit(1)

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    display_name = data.get("model", "") or data.get("env", {}).get("ANTHROPIC_MODEL", model_name)
    return display_name, settings_path.resolve()


def load_cases(cases_dir: Path, filter_pattern: Optional[str] = None) -> list[TestCase]:
    import yaml

    cases: list[TestCase] = []
    for yaml_file in sorted(cases_dir.rglob("*.yaml")):
        rel = str(yaml_file.relative_to(cases_dir))
        if filter_pattern and filter_pattern not in rel:
            continue
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cases.append(TestCase.from_yaml(data))
    return cases


async def run_single(
    driver: SkillTestDriver,
    case: TestCase,
    run_index: int,
    validator: HardConstraintValidator,
    parser: TranscriptParser,
    verbose: bool = False,
    report_dir: Optional[Path] = None,
    model: str = "",
) -> TestResult:
    run_result = await driver.run_case(case, run_index)

    if not run_result.success:
        if verbose:
            from eval.models import HardResult
            print_verbose_summary(case, None, HardResult.skip("执行失败"), "FAIL", run_result.duration, error=run_result.error)
        return TestResult(
            case_id=case.id,
            verdict=Verdict.FAIL,
            duration=run_result.duration,
            error=run_result.error,
        )

    if not run_result.transcript_path or not Path(run_result.transcript_path).is_file():
        if verbose:
            from eval.models import HardResult
            print_verbose_summary(case, None, HardResult.skip("无 transcript"), "FAIL", run_result.duration, error="Transcript not found")
        return TestResult(
            case_id=case.id,
            verdict=Verdict.FAIL,
            duration=run_result.duration,
            error="Transcript not found",
        )

    try:
        transcript = parser.parse(Path(run_result.transcript_path))
    except (ValueError, FileNotFoundError) as e:
        return TestResult(
            case_id=case.id,
            verdict=Verdict.FAIL,
            duration=run_result.duration,
            error=str(e),
        )
    hard_result = validator.check(transcript, case)

    if hard_result.skipped:
        verdict = Verdict.SKIP
    elif hard_result.all_pass():
        verdict = Verdict.PASS
    else:
        verdict = Verdict.FAIL

    soft_result = None
    if verdict == Verdict.PASS:
        from eval.validator.soft_judge import judge_soft
        soft_result = judge_soft(case, transcript.all_text())

    verdict_str = verdict.value
    if verbose:
        print_verbose_summary(case, transcript, hard_result, verdict_str, run_result.duration, soft_result=soft_result)
    if report_dir:
        write_case_report(case, transcript, hard_result, verdict_str, run_result.duration, report_dir, model=model, soft_result=soft_result)

    return TestResult(
        case_id=case.id,
        verdict=verdict,
        hard_result=hard_result,
        transcript_path=run_result.transcript_path,
        duration=run_result.duration,
        soft_result=soft_result,
    )


def analyze_case(case: TestCase, results: list[TestResult]) -> CaseVerdict:
    total = len(results)
    if total == 0:
        return CaseVerdict(case_id=case.id, priority=case.priority, verdict=Verdict.FAIL)

    skip_count = sum(1 for r in results if r.verdict == Verdict.SKIP)
    pass_count = sum(1 for r in results if r.verdict == Verdict.PASS)
    fail_count = sum(1 for r in results if r.verdict == Verdict.FAIL)

    trigger_rate = (total - skip_count) / total
    pass_rate = pass_count / total if total > 0 else 0.0

    if pass_count == total:
        verdict = Verdict.PASS
    elif skip_count == total:
        verdict = Verdict.SKIP
    elif fail_count == 0 and pass_count > 0:
        verdict = Verdict.PASS
    elif pass_count > 0 and fail_count > 0:
        verdict = Verdict.UNSTABLE
    else:
        verdict = Verdict.FAIL

    detail = f"{pass_count}/{total} pass"
    if skip_count:
        detail += f", {skip_count}/{total} skip"
    if fail_count:
        detail += f", {fail_count}/{total} fail"

    soft_scores = [
        r.soft_result.weighted_score() for r in results
        if r.soft_result and not r.soft_result.skipped
    ]
    avg_soft = sum(soft_scores) / len(soft_scores) if soft_scores else None

    return CaseVerdict(
        case_id=case.id,
        priority=case.priority,
        verdict=verdict,
        trigger_rate=trigger_rate,
        pass_rate=pass_rate,
        detail=detail,
        runs=results,
        avg_soft_score=avg_soft,
    )


def check_pass_criteria(verdicts: list[CaseVerdict]) -> tuple[bool, list[str]]:
    """Check pass criteria from 迭代工作流. Returns (passed, messages)."""
    messages: list[str] = []
    all_ok = True

    # Trigger rate >= 90%
    total_runs = sum(len(v.runs) for v in verdicts)
    triggered_runs = sum(
        sum(1 for r in v.runs if r.verdict != Verdict.SKIP) for v in verdicts
    )
    trigger_rate = triggered_runs / total_runs if total_runs > 0 else 0.0
    if trigger_rate >= 0.9:
        messages.append(f"  ✅ 触发率:          {trigger_rate:.0%} ({triggered_runs}/{total_runs})          要求: >= 90%")
    else:
        messages.append(f"  ❌ 触发率:          {trigger_rate:.0%} ({triggered_runs}/{total_runs})          要求: >= 90%")
        all_ok = False

    # P0: every repetition must be PASS (SKIP does not count as PASS)
    p0_cases = [v for v in verdicts if v.priority == "P0"]
    p0_strict_pass = sum(
        1 for v in p0_cases
        if all(r.verdict == Verdict.PASS for r in v.runs)
    )
    if p0_cases:
        if p0_strict_pass == len(p0_cases):
            messages.append(f"  ✅ P0 硬约束:       {p0_strict_pass}/{len(p0_cases)} 全通过          要求: 全部 3/3")
        else:
            messages.append(f"  ❌ P0 硬约束:       {p0_strict_pass}/{len(p0_cases)} 全通过          要求: 全部 3/3")
            all_ok = False
    else:
        messages.append(f"  ─  P0 硬约束:       N/A                 要求: 全部 3/3")

    # P1: at least 2/3
    p1_cases = [v for v in verdicts if v.priority == "P1"]
    if p1_cases:
        p1_ok = sum(1 for v in p1_cases if v.pass_rate >= 2.0 / 3.0)
        if p1_ok == len(p1_cases):
            messages.append(f"  ✅ P1 硬约束:       {p1_ok}/{len(p1_cases)} 达标            要求: >= 2/3")
        else:
            messages.append(f"  ❌ P1 硬约束:       {p1_ok}/{len(p1_cases)} 达标            要求: >= 2/3")
            all_ok = False
    else:
        messages.append(f"  ─  P1 硬约束:       N/A                 要求: >= 2/3")

    # Stability: no UNSTABLE
    unstable_cases = [v for v in verdicts if v.verdict == Verdict.UNSTABLE]
    if not unstable_cases:
        messages.append(f"  ✅ 稳定性:          无 UNSTABLE         要求: 无 UNSTABLE")
    else:
        names = ", ".join(v.case_id for v in unstable_cases)
        messages.append(f"  ❌ 稳定性:          {len(unstable_cases)} UNSTABLE ({names})")
        all_ok = False

    # Soft score (P2 — warning only, does not block)
    soft_scores = [v.avg_soft_score for v in verdicts if v.avg_soft_score is not None]
    if soft_scores:
        avg = sum(soft_scores) / len(soft_scores)
        if avg >= 3.5:
            messages.append(f"  ✅ 软分均值:        {avg:.2f}              要求: >= 3.5")
        else:
            messages.append(f"  ⚠️  软分均值:        {avg:.2f}              要求: >= 3.5")
    else:
        messages.append(f"  ─  软分均值:        N/A                 要求: >= 3.5")

    return all_ok, messages


def _serialize_soft(soft_result) -> dict | None:
    if not soft_result or soft_result.skipped:
        return None
    return {
        "conciseness": soft_result.conciseness,
        "correctness": soft_result.correctness,
        "naturalness": soft_result.naturalness,
        "ux": soft_result.ux,
        "weighted": soft_result.weighted_score(),
        "issues": soft_result.issues,
    }


def _aggregate_soft_scores(v: CaseVerdict) -> dict | None:
    valid = [r.soft_result for r in v.runs if r.soft_result and not r.soft_result.skipped]
    if not valid:
        return None
    n = len(valid)
    return {
        "conciseness": sum(s.conciseness for s in valid) / n,
        "correctness": sum(s.correctness for s in valid) / n,
        "naturalness": sum(s.naturalness for s in valid) / n,
        "ux": sum(s.ux for s in valid) / n,
        "weighted": v.avg_soft_score,
    }


def save_results(
    version: str, model: str, verdicts: list[CaseVerdict], passed: bool, results_dir: Path
) -> Path:
    now = datetime.now(timezone.utc)
    version_dir = results_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)
    output_path = version_dir / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}.json"

    total_runs = sum(len(v.runs) for v in verdicts)
    all_soft = [v.avg_soft_score for v in verdicts if v.avg_soft_score is not None]
    global_soft = sum(all_soft) / len(all_soft) if all_soft else None

    data = {
        "version": version,
        "model": model,
        "timestamp": now.isoformat(),
        "summary": {
            "total_cases": len(verdicts),
            "total_runs": total_runs,
            "trigger_rate": sum(v.trigger_rate for v in verdicts) / len(verdicts) if verdicts else 0,
            "pass": sum(1 for v in verdicts if v.verdict == Verdict.PASS),
            "fail": sum(1 for v in verdicts if v.verdict == Verdict.FAIL),
            "skip": sum(1 for v in verdicts if v.verdict == Verdict.SKIP),
            "unstable": sum(1 for v in verdicts if v.verdict == Verdict.UNSTABLE),
            "verdict": "PASS" if passed else "BLOCK",
            "avg_soft_score": global_soft,
        },
        "cases": {
            v.case_id: {
                "priority": v.priority,
                "verdict": v.verdict.value,
                "trigger_rate": v.trigger_rate,
                "pass_rate": v.pass_rate,
                "soft_scores": _aggregate_soft_scores(v),
                "detail": v.detail,
                "runs": [
                    {
                        "verdict": r.verdict.value,
                        "duration": r.duration,
                        "transcript": r.transcript_path,
                        "error": r.error,
                        "hard_results": [
                            {"rule": rr.rule_id, "passed": rr.passed, "message": rr.message, "description": rr.description}
                            for rr in r.hard_result.results
                        ],
                        "soft_result": _serialize_soft(r.soft_result),
                    }
                    for r in v.runs
                ],
            }
            for v in verdicts
        },
    }

    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def format_run_indicator(results: list[TestResult]) -> str:
    chars = []
    for r in results:
        if r.verdict == Verdict.PASS:
            chars.append(".")
        elif r.verdict == Verdict.FAIL:
            chars.append("F")
        elif r.verdict == Verdict.SKIP:
            chars.append("S")
        else:
            chars.append("?")
    return "".join(chars)


async def main(args: argparse.Namespace) -> int:
    model_display, model_settings_path = resolve_model_settings(args.model)
    cases_dir = Path(__file__).resolve().parent / "cases"
    results_dir = Path(__file__).resolve().parent / "results"

    cases = load_cases(cases_dir, args.cases)
    if not cases:
        print("No test cases found.")
        return 1

    print(f"Skill Evaluation Harness v{VERSION}")
    print(f"Model: {model_display or '(global default)'}")
    if model_settings_path:
        print(f"Settings: {model_settings_path}")
    print(f"Cases: {len(cases)} | Repeat: {args.repeat} | Version: {args.version}")
    print()

    if args.dry_run:
        for case in cases:
            print(f"  [{case.id}] {case.name} ({case.priority})")
        print(f"\nDry run: {len(cases)} cases loaded, 0 executed.")
        return 0

    driver = SkillTestDriver(
        skill_source=SKILL_SOURCE,
        work_dir=results_dir / args.version / "workspaces",
        model_settings=model_settings_path,
        max_turns=args.max_turns,
        timeout=args.timeout,
    )
    parser = TranscriptParser()
    validator = HardConstraintValidator()

    verdicts: list[CaseVerdict] = []

    report_dir = results_dir / args.version / "reports" if args.verbose else None

    for case in cases:
        results: list[TestResult] = []
        for i in range(args.repeat):
            result = await run_single(
                driver, case, i, validator, parser,
                verbose=args.verbose, report_dir=report_dir, model=model_display,
            )
            results.append(result)

        case_verdict = analyze_case(case, results)
        verdicts.append(case_verdict)

        indicator = format_run_indicator(results)
        verdict_str = case_verdict.verdict.value
        soft_tag = f" soft={case_verdict.avg_soft_score:.1f}" if case_verdict.avg_soft_score is not None else ""
        print(f"[{case.id:<35}] {indicator:<5} {verdict_str:<9} ({case_verdict.detail}){soft_tag}")

    print()
    print("═" * 56)
    print("通过条件检查：")

    passed, messages = check_pass_criteria(verdicts)
    for msg in messages:
        print(msg)

    print("─" * 56)
    if passed:
        print("结论: PASS — 可合并")
    else:
        failed_p0 = [v for v in verdicts if v.priority == "P0" and v.verdict != Verdict.PASS]
        if failed_p0:
            names = ", ".join(v.case_id for v in failed_p0)
            print(f"结论: BLOCK — P0 用例 {names} 未全通过")
        else:
            print("结论: BLOCK — 未满足通过条件")
    print("═" * 56)

    output_path = save_results(args.version, model_display, verdicts, passed, results_dir)
    print(f"\nResults: {output_path}")

    if args.set_baseline and passed:
        baseline_link = results_dir / "baseline"
        if baseline_link.is_symlink() or baseline_link.exists():
            baseline_link.unlink()
        baseline_link.symlink_to(args.version)
        print(f"Baseline updated: baseline -> {args.version}")
    elif args.set_baseline and not passed:
        print("Baseline NOT updated (run did not pass)")

    return 0 if passed else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skill Evaluation Harness")
    parser.add_argument("--version", required=True, help="Version label for this run")
    parser.add_argument("--repeat", type=int, default=3, help="Repetitions per case (default: 3)")
    parser.add_argument("--cases", default=None, help="Filter cases by path pattern")
    parser.add_argument("--model", default=None, help="Model config name (file in eval/models/) or path to settings JSON")
    parser.add_argument("--timeout", type=int, default=120, help="Execution timeout in seconds")
    parser.add_argument("--max-turns", type=int, default=100, help="Max turns for Claude CLI")
    parser.add_argument("--verbose", action="store_true", help="Show failure details")
    parser.add_argument("--dry-run", action="store_true", help="Load cases without executing")
    parser.add_argument("--set-baseline", action="store_true", help="Set this version as baseline if passed")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(main(args)))
