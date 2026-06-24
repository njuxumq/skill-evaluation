#!/usr/bin/env python3
"""维度配置工具：校验配置、更新judge_id"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Union

from utils import (
    result,
    VALID_DIMENSION_TYPES,
    BUILTIN_FUNCTIONS,
)
from files import (
    load_json,
    save_json,
)


# ============================================================================
# 校验逻辑
# ============================================================================

def validate_dimension(dim: dict, idx: int) -> List[str]:
    """校验单个维度，返回错误列表"""
    errors = []
    name = dim.get("name", f"index_{idx}")

    if not dim.get("name"):
        errors.append(f"[{idx}] missing 'name'")
    if not dim.get("type"):
        errors.append(f"[{name}] missing 'type'")
        return errors

    dtype = dim["type"]
    if dtype not in VALID_DIMENSION_TYPES:
        errors.append(f"[{name}] invalid type '{dtype}'")
        return errors

    # LLM类维度校验（llm-score 和 llm-judge）
    if dtype in ("llm-score", "llm-judge"):
        # judge_id 必填
        if not dim.get("judge_id"):
            errors.append(f"[{name}] missing 'judge_id'")

        # weight 必填
        w = dim.get("weight")
        if w is None:
            errors.append(f"[{name}] missing 'weight'")
        elif not isinstance(w, (int, float)) or not (0 <= w <= 1):
            errors.append(f"[{name}] invalid weight '{w}'")

        # prompt 必填
        if "prompt" not in dim:
            errors.append(f"[{name}] missing 'prompt'")
        elif isinstance(dim["prompt"], dict):
            for f in ("definition", "instruct", "step"):
                if not dim["prompt"].get(f):
                    errors.append(f"[{name}] prompt.{f} missing")

    # 内置函数校验
    elif dtype == "builtin":
        # judge_id 不应该存在
        if "judge_id" in dim:
            errors.append(f"[{name}] builtin type should not have 'judge_id'")

        # func 必填
        func = dim.get("func")
        if not func:
            errors.append(f"[{name}] missing 'func'")
        elif func not in BUILTIN_FUNCTIONS:
            errors.append(f"[{name}] invalid func '{func}'")

        # weight 必填
        w = dim.get("weight")
        if w is None:
            errors.append(f"[{name}] missing 'weight'")
        elif not isinstance(w, (int, float)) or not (0 <= w <= 1):
            errors.append(f"[{name}] invalid weight '{w}'")

    return errors


def check_config(path: str) -> dict:
    """校验维度配置文件"""
    result_obj = {"success": True, "file": path, "errors": [], "dimensions": []}

    p = Path(path)
    if not p.exists():
        return {**result_obj, "success": False, "errors": [f"file not found: {path}"]}

    # 使用 common.load_json 加载文件
    load_result = load_json(path)
    if not load_result.get("success"):
        return {**result_obj, "success": False, "errors": [load_result.get("message", "load failed")]}

    data = load_result.get("data")

    if not isinstance(data, dict):
        return {**result_obj, "success": False, "errors": ["root must be object"]}

    # 检查根节点字段
    valid_root_fields = {"name", "description", "evals"}
    invalid_root_fields = {"scene", "scene_type", "dimensions"}
    for field in invalid_root_fields:
        if field in data:
            result_obj["errors"].append(f"invalid root field '{field}', use correct field name")

    # 检查维度数组字段
    if "evals" not in data:
        if "dimensions" in data:
            result_obj["errors"].append("'dimensions' is invalid, use 'evals' instead")
        else:
            result_obj["errors"].append("missing 'evals' field")

    dims = data.get("evals", [])
    if not isinstance(dims, list):
        return {**result_obj, "success": False, "errors": ["'evals' must be array"]}

    # 逐个校验
    for i, d in enumerate(dims):
        if not isinstance(d, dict):
            result_obj["errors"].append(f"[{i}] must be object")
            continue

        # 检查是否错误嵌套在 config 内
        if "config" in d and isinstance(d["config"], dict):
            # config 内有 type 字段，说明维度对象嵌套错误
            if "type" in d["config"]:
                name = d.get("name", f"index_{i}")
                result_obj["errors"].append(f"[{name}] dimension fields should not be nested in 'config'")
                # 从 config 中提取字段进行校验
                d = d["config"]

        errs = validate_dimension(d, i)
        result_obj["errors"].extend(errs)
        result_obj["dimensions"].append({"name": d.get("name", f"index_{i}"), "valid": not errs})

    # 检查权重总和（所有维度都应有 weight）
    weight_dims = [d for d in dims if isinstance(d, dict) and "weight" in d]
    if weight_dims:
        total = sum(d["weight"] for d in weight_dims if isinstance(d.get("weight"), (int, float)))
        if abs(total - 1.0) > 0.0001:
            result_obj["errors"].append(f"weight sum {total:.4f} != 1.0")

    if result_obj["errors"]:
        result_obj["success"] = False
    return result_obj


# ============================================================================
# 更新 judge_id
# ============================================================================

def get_judge_id(config: Union[dict, list]) -> Optional[str]:
    """从评委配置中提取judge_id"""
    if isinstance(config, list) and config:
        return config[0].get("id")
    if isinstance(config, dict):
        return config.get("id") or config.get("models", [{}])[0].get("id")
    return None


def update_config(dim_path: str, judge_path: str, output_path: Optional[str]) -> dict:
    """更新维度配置中的judge_id"""
    result_obj = {"success": True, "errors": []}

    # 加载评委配置 - 使用 common.load_json
    judge_result = load_json(judge_path)
    if not judge_result.get("success"):
        return {"success": False, "errors": [f"load judge config failed: {judge_result.get('message')}"]}
    judge_config = judge_result.get("data")

    judge_id = get_judge_id(judge_config)
    if not judge_id:
        return {"success": False, "errors": ["judge_id not found in config"]}
    result_obj["judge_id"] = judge_id

    # 加载维度配置 - 使用 common.load_json
    dim_result = load_json(dim_path)
    if not dim_result.get("success"):
        return {"success": False, "errors": [f"load dimension config failed: {dim_result.get('message')}"]}
    dim_config = dim_result.get("data")

    # 更新judge_id
    updated = 0
    for dim in dim_config.get("evals", []):
        if isinstance(dim, dict) and dim.get("type") in ("llm-score", "llm-judge"):
            dim["judge_id"] = judge_id
            updated += 1

    result_obj["updated"] = updated

    # 保存 - 使用 common.save_json
    out = output_path or dim_path
    save_result = save_json(out, dim_config)
    if not save_result.get("success"):
        result_obj["success"] = False
        result_obj["errors"].append(f"save failed: {save_result.get('message')}")
    else:
        result_obj["output"] = out

    return result_obj


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="维度配置工具")
    parser.add_argument("-a", "--action", required=True, choices=["check", "update"], help="操作类型")
    parser.add_argument("-d", "--dimension", help="维度配置文件")
    parser.add_argument("-j", "--judge", help="评委配置文件（update时必需）")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("--quiet", action="store_true", help="仅输出JSON")
    args = parser.parse_args()

    if args.action == "check":
        if not args.dimension:
            parser.error("--dimension required for check")
        result = check_config(args.dimension)

        if not args.quiet:
            status = "PASS" if result["success"] else f"FAIL ({len(result['errors'])} errors)"
            print(f"Validation: {status}")
            for e in result["errors"]:
                print(f"  - {e}")

    elif args.action == "update":
        if not args.dimension or not args.judge:
            parser.error("--dimension and --judge required for update")
        result = update_config(args.dimension, args.judge, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()