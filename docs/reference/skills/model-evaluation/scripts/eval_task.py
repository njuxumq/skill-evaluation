#!/usr/bin/env python3
"""评测任务管理：提交任务、查询状态、轮询结果"""
import argparse
import json
import time
import requests
from pathlib import Path

from utils import (
    TERMINAL_STATES,
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
from eval_dimension import update_config, check_config


def load_inference_models(inference_models_path: str) -> list:
    """加载推理模型列表，返回顶层 models 格式"""
    if not inference_models_path:
        return []

    result = load_json(inference_models_path)
    if not result.get("success"):
        raise ValueError(f"推理模型文件加载失败: {result.get('message')}")

    selected_models = result.get("data", {})
    models = selected_models.get("models", [])

    # 转换为顶层 models 格式（不含 description，添加 type 默认值）
    return [
        {
            "id": m.get("id"),
            "name": m.get("name"),
            "model": m.get("model"),
            "type": m.get("type", "api-openai")
        }
        for m in models
    ]


def build_inference_template(evalset_id: str, inference_models_path: str) -> dict:
    """构建 inference 模板"""
    if not inference_models_path:
        return None

    result = load_json(inference_models_path)
    if not result.get("success"):
        raise ValueError(f"推理模型文件加载失败: {result.get('message')}")

    selected_models = result.get("data", {})
    models = selected_models.get("models", [])

    return {
        "name": "模型推理",
        "type": "inference",
        "parameters": {
            "evalset": evalset_id,
            "models": [{"id": m.get("id")} for m in models]
        }
    }


# ============================================================================
# 提交任务
# ============================================================================

def cmd_submit(args):
    """提交评测任务"""
    # 验证文件存在
    for f, desc in [(args.eval_set, "评测集"), (args.eval_dimension, "评测维度"), (args.eval_judge, "评委配置")]:
        if not Path(f).exists():
            raise FileNotFoundError(f"{desc}文件不存在: {f}")

    # 步骤1：自动填充 judge_id
    update_result = update_config(args.eval_dimension, args.eval_judge, None)
    if not update_result.get("success"):
        raise ValueError(f"填充judge_id失败: {update_result.get('errors')}")

    # 步骤2：校验维度配置
    check_result = check_config(args.eval_dimension)
    if not check_result.get("success"):
        errors = check_result.get("errors", [])
        raise ValueError(f"维度配置校验失败({len(errors)}个错误): {errors}")

    # 步骤3：提交任务
    config_result = load_config_kv(args.config)
    if not config_result.get("success"):
        raise ValueError(f"配置文件加载失败: {config_result.get('message')}")
    config = config_result.get("data", {})

    # 使用 TokenManager 和 ApiClient
    token_manager = TokenManager(args.auth)
    client = ApiClient(token_manager, config.get('base_url', 'http://127.0.0.1:8080'))

    # 构建请求
    evalset_result = load_json(args.eval_set)
    if not evalset_result.get("success"):
        raise ValueError(f"评测集文件加载失败: {evalset_result.get('message')}")
    evalset_id = evalset_result.get("data", {}).get('dataset')

    dimensions_result = load_json(args.eval_dimension)
    if not dimensions_result.get("success"):
        raise ValueError(f"维度配置加载失败: {dimensions_result.get('message')}")
    dimensions = dimensions_result.get("data", {})

    judges_result = load_json(args.eval_judge)
    if not judges_result.get("success"):
        raise ValueError(f"评委配置加载失败: {judges_result.get('message')}")
    judges = judges_result.get("data", {})

    # 加载推理模型（新增）
    inference_models_list = []
    inference_template = None
    if args.inference_models:
        inference_models_list = load_inference_models(args.inference_models)
        inference_template = build_inference_template(evalset_id, args.inference_models)

    # 构建评委模型列表（移除 description、concurrency、params 字段）
    judge_model = {
        "id": judges.get("id"),
        "name": judges.get("name"),
        "type": judges.get("type", "api-openai"),
        "model": judges.get("model")
    }
    # 移除值为 None 的字段
    judge_model = {k: v for k, v in judge_model.items() if v is not None}
    judge_models = [judge_model] if judges else []

    # 合并模型列表：推理模型 + 评委模型
    all_models = inference_models_list + judge_models

    # 构建 templates 数组
    templates = []
    if inference_template:
        templates.append(inference_template)
    templates.append({
        "name": "模型评测",
        "type": "evaluation",
        "parameters": {"evalset": evalset_id, "eval": dimensions.get("evals")}
    })

    payload = {
        "apiVersion": "v1",
        "models": all_models,
        "agents": [],
        "spec": {
            "templates": templates
        }
    }

    task_data = client.post("/open/api/v1/eval/tasks", json=payload)

    save_json(args.output, {"task_id": task_data.get('id'), "evalset_id": evalset_id})
    return {"task_id": task_data.get('id'), "status": task_data.get('status')}


# ============================================================================
# 查询状态
# ============================================================================

def check_status(task_id: str, client: ApiClient, output_file: str) -> dict:
    """查询单次任务状态"""
    task_data = client.get(f"/open/api/v1/eval/tasks/{task_id}")
    status = task_data.get('status')

    result = {"task_id": task_id, "status": status}

    # 成功时下载报告
    if status == 'Succeeded':
        artifacts = {a['type']: a['url'] for a in task_data.get('artifacts', [])}
        report_url = artifacts.get('report_file')

        if report_url:
            resp = requests.get(report_url)
            resp.raise_for_status()
            save_json(output_file, resp.json())

        result["platform_url"] = artifacts.get('platform_page')
        result["report_file"] = output_file if report_url else None

    return result


def cmd_status(args):
    """查询任务状态"""
    config_result = load_config_kv(args.config)
    if not config_result.get("success"):
        raise ValueError(f"配置文件加载失败: {config_result.get('message')}")
    config = config_result.get("data", {})

    # 使用 TokenManager 和 ApiClient
    token_manager = TokenManager(args.auth)
    client = ApiClient(token_manager, config.get('base_url', 'http://127.0.0.1:8080'))

    evaltask_result = load_json(args.evaltask)
    if not evaltask_result.get("success"):
        raise ValueError(f"任务元信息加载失败: {evaltask_result.get('message')}")
    task_id = evaltask_result.get("data", {}).get('task_id')
    if not task_id:
        raise ValueError("评测任务元信息文件中未找到task_id")

    # 轮询模式
    if args.poll:
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > args.timeout:
                return {"task_id": task_id, "status": "Timeout", "error": f"轮询超时（{args.timeout}秒）"}

            result_obj = check_status(task_id, client, args.output)

            if result_obj["status"] in TERMINAL_STATES:
                return result_obj

            print(json.dumps({"task_id": task_id, "status": result_obj["status"], "elapsed": int(elapsed),
                              "message": f"任务执行中，{args.interval}秒后重试..."}, ensure_ascii=False), flush=True)
            time.sleep(args.interval)

    return check_status(task_id, client, args.output)


# ============================================================================
# 结果摘要
# ============================================================================

def extract_text_from_content(content: list) -> str:
    """递归提取 content 中的文本"""
    texts = []
    for item in content:
        if item.get('type') == 'paragraph' and item.get('text'):
            texts.append(item['text'])
        elif item.get('type') in ('section',) and item.get('content'):
            texts.extend(extract_text_from_content(item['content']))
    return '\n'.join(texts)


def find_section_by_title(content: list, title: str) -> dict:
    """根据标题查找 section"""
    for item in content:
        if item.get('type') == 'section':
            if item.get('title') == title:
                return item
            if item.get('content'):
                result = find_section_by_title(item['content'], title)
                if result:
                    return result
    return None


def find_table_by_title(content: list, title: str) -> list:
    """根据标题查找表格数据"""
    for item in content:
        if item.get('type') == 'table' and title in item.get('title', ''):
            return item.get('dataset', {}).get('source', [])
        if item.get('type') == 'section' and item.get('content'):
            result = find_table_by_title(item['content'], title)
            if result:
                return result
    return []


def cmd_summary(args):
    """生成评测结果摘要"""
    result_file = Path(args.result)
    if not result_file.exists():
        raise FileNotFoundError(f"评测结果文件不存在: {result_file}")

    load_result = load_json(args.result)
    if not load_result.get("success"):
        raise ValueError(f"评测结果加载失败: {load_result.get('message')}")
    data = load_result.get("data", {})
    output = []

    # 1. 综合得分 (从顶层 metric.aggregations 中提取)
    aggregations = data.get('metric', {}).get('aggregations', [])

    if aggregations:
        output.append("## 综合得分")
        output.append("| 模型 | 分类 | 综合得分 |")
        output.append("|------|------|----------|")

        for agg in aggregations:
            if agg.get('name') == '综合得分':
                for group in agg.get('groups', []):
                    model = category = ""
                    for g in group.get('group', []):
                        if g.get('g') == 'model':
                            model = g.get('v', '')
                        elif g.get('g') == 'category':
                            category = g.get('v', '')
                    score = group.get('payload', {}).get('average', 0)
                    output.append(f"| {model} | {category} | {score:.2f} |")
        output.append("")

    # 2. 各维度表现
    summary = data.get('summary', {})
    content = summary.get('content', [])

    # 查找综合得分表格
    score_table = find_table_by_title(content, '综合得分')
    if score_table and len(score_table) > 1:
        output.append("## 各维度得分")
        headers = score_table[0]
        rows = score_table[1:]
        output.append("| " + " | ".join(headers[:5]) + " |")
        output.append("| " + " | ".join(["---"] * min(5, len(headers))) + " |")
        for row in rows[:10]:  # 限制显示前10行
            output.append("| " + " | ".join(str(v) if isinstance(v, (int, float)) else v for v in row[:5]) + " |")
        output.append("")

    # 查找良好率表格
    good_rate_table = find_table_by_title(content, '良好率')
    if good_rate_table and len(good_rate_table) > 1:
        output.append("## 良好率")
        headers = good_rate_table[0]
        rows = good_rate_table[1:]
        output.append("| " + " | ".join(headers) + " |")
        output.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows[:5]:  # 限制显示前5行
            output.append("| " + " | ".join(f"{v:.1f}" if isinstance(v, float) else str(v) for v in row) + " |")
        output.append("")

    # 3. 改进建议
    suggestion_section = find_section_by_title(content, '2.3 改进建议')
    if suggestion_section:
        suggestion_text = extract_text_from_content(suggestion_section.get('content', []))
        if suggestion_text:
            output.append("## 改进建议")
            output.append(suggestion_text)
            output.append("")

    # 4. 在线报告链接
    if args.platform_url:
        output.append("## 在线报告")
        output.append(args.platform_url)

    return {"summary": "\n".join(output)}


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='评测任务管理')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # submit
    p = subparsers.add_parser('submit', help='提交评测任务')
    p.add_argument('--config', required=True, help='服务配置文件')
    p.add_argument('--auth', required=True, help='鉴权信息文件')
    p.add_argument('--eval_set', required=True, help='评测集标识文件')
    p.add_argument('--eval_dimension', required=True, help='评测维度配置文件')
    p.add_argument('--eval_judge', required=True, help='评委配置文件')
    p.add_argument('--output', required=True, help='评测任务元信息输出文件')
    p.add_argument('--inference_models', default=None, help='推理模型列表文件(selected-models.json，可选)')
    p.set_defaults(func=cmd_submit)

    # status
    p = subparsers.add_parser('status', help='查询任务状态')
    p.add_argument('--config', required=True, help='服务配置文件')
    p.add_argument('--auth', required=True, help='鉴权信息文件')
    p.add_argument('--evaltask', required=True, help='评测任务元信息文件')
    p.add_argument('--output', required=True, help='评测报告输出路径')
    p.add_argument('--poll', action='store_true', help='启用自动轮询模式')
    p.add_argument('--interval', type=int, default=30, help='轮询间隔秒数')
    p.add_argument('--timeout', type=int, default=3600, help='轮询超时秒数')
    p.set_defaults(func=cmd_status)

    # summary
    p = subparsers.add_parser('summary', help='生成评测结果摘要')
    p.add_argument('--result', required=True, help='评测结果文件(evaltask-result.json)')
    p.add_argument('--platform_url', default='', help='在线报告链接(可选)')
    p.set_defaults(func=cmd_summary)

    args = parser.parse_args()

    # Python 3.6 兼容：手动检查子命令
    if args.command is None:
        parser.error("请指定子命令: submit, status, summary")

    try:
        result_obj = args.func(args)
        print(json.dumps(result_obj, ensure_ascii=False))
    except Exception as e:
        handle_cli_error(e)


if __name__ == '__main__':
    main()