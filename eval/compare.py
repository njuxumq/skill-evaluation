"""Version comparator: detects regressions between baseline and candidate runs.

Usage:
    python eval/compare.py --baseline v2.0 --candidate v2.1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_latest_run(version: str) -> Optional[dict]:
    version_dir = RESULTS_DIR / version
    if not version_dir.is_dir():
        return None
    runs = sorted(version_dir.glob("run_*.json"))
    if not runs:
        return None
    return json.loads(runs[-1].read_text(encoding="utf-8"))


def compare(baseline: dict, candidate: dict) -> dict:
    report = {
        "baseline_version": baseline["version"],
        "candidate_version": candidate["version"],
        "regressions": [],
        "trigger_regressions": [],
        "improvements": [],
        "trigger_deltas": {},
        "verdict": "",
    }

    baseline_cases = baseline.get("cases", {})
    candidate_cases = candidate.get("cases", {})

    all_ids = set(baseline_cases.keys()) | set(candidate_cases.keys())

    for case_id in sorted(all_ids):
        old = baseline_cases.get(case_id)
        new = candidate_cases.get(case_id)

        if not old or not new:
            continue

        old_verdict = old["verdict"]
        new_verdict = new["verdict"]

        # Behavior regression: PASS -> FAIL
        if old_verdict == "PASS" and new_verdict == "FAIL":
            report["regressions"].append({
                "case_id": case_id,
                "old": old_verdict,
                "new": new_verdict,
                "detail": new.get("detail", ""),
            })
        # Trigger regression: PASS -> SKIP
        elif old_verdict == "PASS" and new_verdict == "SKIP":
            report["trigger_regressions"].append({
                "case_id": case_id,
                "old": old_verdict,
                "new": new_verdict,
            })
        # Stability regression: PASS -> UNSTABLE
        elif old_verdict == "PASS" and new_verdict == "UNSTABLE":
            report["regressions"].append({
                "case_id": case_id,
                "old": old_verdict,
                "new": new_verdict,
                "detail": new.get("detail", ""),
            })
        # Improvement: FAIL/SKIP -> PASS
        elif old_verdict in ("FAIL", "SKIP", "UNSTABLE") and new_verdict == "PASS":
            report["improvements"].append({
                "case_id": case_id,
                "old": old_verdict,
                "new": new_verdict,
            })

        # Trigger rate delta
        old_tr = old.get("trigger_rate")
        new_tr = new.get("trigger_rate")
        if old_tr is not None and new_tr is not None:
            delta = new_tr - old_tr
            if abs(delta) > 0.01:
                report["trigger_deltas"][case_id] = {
                    "old": old_tr,
                    "new": new_tr,
                    "delta": delta,
                }

    # Soft score delta
    report["soft_delta"] = _compute_soft_delta(baseline_cases, candidate_cases)

    # Verdict (三级: BLOCK > WARNING > PASS)
    if report["regressions"] or report["trigger_regressions"]:
        report["verdict"] = "BLOCK"
    elif report["soft_delta"].get("weighted", {}).get("delta", 0) < -0.1:
        report["verdict"] = "WARNING"
    else:
        report["verdict"] = "PASS"

    return report


def _compute_soft_delta(baseline_cases: dict, candidate_cases: dict) -> dict:
    dims = ("conciseness", "correctness", "naturalness", "ux", "weighted")
    baseline_scores: dict[str, list[float]] = {d: [] for d in dims}
    candidate_scores: dict[str, list[float]] = {d: [] for d in dims}

    for case_id in set(baseline_cases) & set(candidate_cases):
        b_soft = baseline_cases[case_id].get("soft_scores")
        c_soft = candidate_cases[case_id].get("soft_scores")
        if b_soft and c_soft:
            for d in dims:
                if b_soft.get(d) is not None and c_soft.get(d) is not None:
                    baseline_scores[d].append(b_soft[d])
                    candidate_scores[d].append(c_soft[d])

    deltas: dict = {}
    for d in dims:
        if baseline_scores[d]:
            b_avg = sum(baseline_scores[d]) / len(baseline_scores[d])
            c_avg = sum(candidate_scores[d]) / len(candidate_scores[d])
            deltas[d] = {"baseline": b_avg, "candidate": c_avg, "delta": c_avg - b_avg}
    return deltas


def print_report(report: dict) -> None:
    bl = report["baseline_version"]
    cd = report["candidate_version"]
    regressions = report["regressions"]
    trigger_regressions = report["trigger_regressions"]
    improvements = report["improvements"]

    print("=" * 60)
    print(f"  Skill 迭代验证报告：{bl} -> {cd}")
    print("=" * 60)
    print()

    if regressions:
        print(f"  回归（必须修复）：{len(regressions)} 个")
        print("  " + "-" * 56)
        for r in regressions:
            print(f"  [{r['case_id']}]")
            print(f"    {bl}: {r['old']}")
            print(f"    {cd}: {r['new']} ({r['detail']})")
        print()

    if trigger_regressions:
        print(f"  触发回归：{len(trigger_regressions)} 个")
        print("  " + "-" * 56)
        for r in trigger_regressions:
            print(f"  [{r['case_id']}]")
            print(f"    {bl}: {r['old']} -> {cd}: {r['new']} (Skill 不再被触发)")
        print()

    if improvements:
        print(f"  改进：{len(improvements)} 个")
        print("  " + "-" * 56)
        for r in improvements:
            print(f"  [{r['case_id']}]  {r['old']} -> {r['new']}")
        print()

    if report["trigger_deltas"]:
        print("  触发率变化：")
        for case_id, td in report["trigger_deltas"].items():
            sign = "+" if td["delta"] > 0 else ""
            print(f"    {case_id}: {td['old']:.0%} -> {td['new']:.0%} ({sign}{td['delta']:.0%})")
        print()

    if not regressions and not trigger_regressions and not improvements:
        print("  无变化 - baseline 与 candidate 结果一致")
        print()

    soft_delta = report.get("soft_delta", {})
    if soft_delta:
        _DIM_NAMES = {"conciseness": "简洁度", "correctness": "正确性", "naturalness": "自然度", "ux": "体验", "weighted": "加权"}
        print("  软分变化（平均）：")
        for dim in ("conciseness", "correctness", "naturalness", "ux", "weighted"):
            d = soft_delta.get(dim)
            if d:
                sign = "+" if d["delta"] >= 0 else ""
                warn = " ← 注意" if d["delta"] < -0.1 else ""
                print(f"    {_DIM_NAMES[dim]:　<4}: {d['baseline']:.1f} -> {d['candidate']:.1f} ({sign}{d['delta']:.1f}){warn}")
        print()

    print("  " + "-" * 56)
    if report["verdict"] == "BLOCK":
        print("  结论: BLOCK - 存在回归，修复后重新验证")
    elif report["verdict"] == "WARNING":
        print("  结论: WARNING - 软分整体下降，建议检查")
    else:
        print("  结论: PASS - 无回归，可合并")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare baseline vs candidate results")
    parser.add_argument("--baseline", required=True, help="Baseline version label")
    parser.add_argument("--candidate", required=True, help="Candidate version label")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted report")
    args = parser.parse_args()

    baseline_data = load_latest_run(args.baseline)
    if not baseline_data:
        print(f"Baseline not found: {args.baseline}")
        print(f"  Expected: {RESULTS_DIR / args.baseline}/run_*.json")
        return 1

    candidate_data = load_latest_run(args.candidate)
    if not candidate_data:
        print(f"Candidate not found: {args.candidate}")
        print(f"  Expected: {RESULTS_DIR / args.candidate}/run_*.json")
        return 1

    report = compare(baseline_data, candidate_data)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
