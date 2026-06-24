#!/usr/bin/env python3
"""评测模型管理：获取模型列表、选择模型"""
import argparse
import json
import sys
from pathlib import Path

from utils import (
    handle_cli_error,
)
from files import (
    load_json,
    save_json,
    load_config_kv,
)
from clients import (
    ApiClient,
    TokenManager,
)


def cmd_list_models(args):
    """获取可用推理模型详情列表"""
    config_result = load_config_kv(args.config)
    if not config_result.get("success"):
        raise ValueError(f"配置文件加载失败: {config_result.get('message')}")
    config = config_result.get("data", {})

    # 使用 TokenManager 和 ApiClient
    token_manager = TokenManager(args.auth)
    client = ApiClient(token_manager, config.get('base_url', 'http://127.0.0.1:8080'))

    models = client.get_models_detail()

    save_json(args.output, {"models": models})
    return {"models": models, "output": args.output}


def cmd_select_models(args):
    """根据用户选择生成 selected-models.json

    支持两种选择方式：
    - 序号选择：如 "1,2" 或 "1,2,3"
    - 模型名称：如 "deepseek-chat,spark-lite"
    """
    # 加载可用模型列表
    models_result = load_json(args.input)
    if not models_result.get("success"):
        raise ValueError(f"模型列表加载失败: {models_result.get('message')}")
    models_data = models_result.get("data", {})
    available_models = models_data.get("models", [])
    if not available_models:
        raise ValueError("可用模型列表为空")

    # 解析用户选择
    selected = []
    selection_parts = [s.strip() for s in args.selection.split(",")]

    for part in selection_parts:
        if not part:
            continue
        # 尝试作为序号解析
        if part.isdigit():
            idx = int(part) - 1  # 用户输入从1开始
            if 0 <= idx < len(available_models):
                selected.append(available_models[idx])
            else:
                raise ValueError(f"无效的模型序号: {part}，有效范围 1-{len(available_models)}")
        else:
            # 作为模型名称匹配
            matched = None
            for m in available_models:
                if m.get("model") == part or m.get("name") == part:
                    matched = m
                    break
            if matched:
                selected.append(matched)
            else:
                raise ValueError(f"未找到模型: {part}")

    if not selected:
        raise ValueError("未选择任何模型")

    # 判断模式
    mode = "single" if len(selected) == 1 else "multi"

    # 保存结果
    result = {
        "models": selected,
        "mode": mode
    }
    save_json(args.output, result)

    # 返回简要信息
    model_names = [m.get("name", m.get("model", "unknown")) for m in selected]
    return {
        "success": True,
        "selected_models": model_names,
        "mode": mode,
        "output": args.output
    }


def main():
    parser = argparse.ArgumentParser(description='评测模型管理')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # list-models
    p = subparsers.add_parser('list-models', help='获取可用推理模型列表')
    p.add_argument('--auth', required=True, help='鉴权信息文件')
    p.add_argument('--config', required=True, help='服务配置文件')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_list_models)

    # select-models
    p = subparsers.add_parser('select-models', help='选择推理模型')
    p.add_argument('--input', required=True, help='可用模型列表文件路径')
    p.add_argument('--selection', required=True, help='模型选择（序号如 1,2 或模型名称如 deepseek-chat,spark-lite）')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_select_models)

    args = parser.parse_args()

    # Python 3.6 兼容：手动检查子命令
    if args.command is None:
        parser.error("请指定子命令: list-models, select-models")

    try:
        result_obj = args.func(args)
        print(json.dumps(result_obj, ensure_ascii=False))
    except Exception as e:
        handle_cli_error(e)


if __name__ == '__main__':
    main()