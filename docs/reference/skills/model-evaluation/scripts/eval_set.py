#!/usr/bin/env python3
"""评测集管理：解析、标准化、提交"""
import argparse
import json
import math
import random
import string
import sys
from pathlib import Path

from utils import (
    OPTIONAL_FIELDS,
    ERR_REMOTE_DEFAULT,
    handle_cli_error,
)
from files import (
    load_json,
    save_json,
    load_config_kv,
    load_data,
    load_jsonl_stream,
    extract_fields,
)
from clients import (
    ApiClient,
    TokenManager,
)


def cmd_analysis(args):
    """解析评测集文件结构，输出结构文件

    产物：evalset-structure.json（包含文件格式、行数、字段信息）

    字段映射由 Claude Code 根据规则生成，不再由脚本推断。
    """
    load_result = load_data(args.input)
    if not load_result.get("success"):
        raise ValueError(f"数据加载失败: {load_result.get('message')}")
    data = load_result.get("data", {}).get("items", [])

    fields = extract_fields(data)

    # 结构文件：唯一产物
    structure = {
        "file": args.input,
        "format": Path(args.input).suffix.lower()[1:],
        "total_rows": len(data),
        "fields": fields
    }
    save_json(args.output, structure)

    return {
        "success": True,
        "total_rows": len(data),
        "fields": list(fields.keys()),
        "structure_file": args.output
    }


def analyze_answer_with_mapping(data: list, mapping: dict) -> dict:
    """结合映射配置分析 answer 字段状态

    Args:
        data: 原始评测集数据列表
        mapping: 字段映射配置（已确认）

    Returns:
        {"exists": bool, "source_field": str|null, "status": "all_empty"|"partial"|"all_filled"}
    """
    answer_config = mapping.get('answer', {})
    if isinstance(answer_config, str):
        source_field = answer_config
    else:
        source_field = answer_config.get('source_field')

    if not source_field:
        return {"exists": False, "source_field": None, "status": "all_empty"}

    # 检查原始数据中该字段状态
    empty_count = 0
    for item in data:
        answer_value = item.get(source_field)
        if is_empty_value(answer_value):
            empty_count += 1

    total = len(data)
    if empty_count == total:
        status = "all_empty"
    elif empty_count == 0:
        status = "all_filled"
    else:
        status = "partial"

    return {"exists": True, "source_field": source_field, "status": status}


# ============================================================================
# 标准化
# ============================================================================

# 空值判断辅助函数
def is_empty_value(value) -> bool:
    """判断值是否为空（包括各种空值形式）

    检测以下空值形式：
    - None：Python 空值
    - NaN：pandas 读取 Excel 空单元格产生的 float nan
    - 空字符串：去除空白后为空
    - 空值字符串："null"、"nan"、"none"、"n/a"（大小写不敏感）
    """
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    str_val = str(value).strip().lower()
    if str_val == '':
        return True
    # 检测常见空值字符串
    if str_val in ('null', 'nan', 'none', 'n/a'):
        return True
    return False


def extract_field_value(item: dict, mapping: dict, field_name: str) -> str:
    """根据映射配置提取字段值

    Args:
        item: 原始数据项
        mapping: 字段映射配置
        field_name: 标准字段名

    Returns:
        字段值（字符串）
    """
    config = mapping.get(field_name, {})
    if isinstance(config, str):
        # 兼容旧格式
        src_field = config
        default_val = None
    else:
        src_field = config.get('source_field')
        default_val = config.get('default')

    if src_field and src_field in item:
        value = item.get(src_field)
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            return str(value).strip()

    if default_val:
        return str(default_val)

    return ""


def expand_data(data: list, mapping: dict, models: list) -> list:
    """展开评测集：N问题 × M模型 = N×M条记录

    Args:
        data: 原始评测集数据
        mapping: 字段映射配置
        models: 用户选择的模型列表，每项为 {"name", "model", "id", ...}

    Returns:
        展开后的标准化评测集（不含 metainfo，由 submit 阶段填充）
    """
    result = []
    case_counter = 0
    question_to_case = {}

    for item in data:
        question = extract_field_value(item, mapping, 'question')
        if not question:
            continue

        # 生成 case_id（同一问题共享）
        if question not in question_to_case:
            case_counter += 1
            question_to_case[question] = f'case-{case_counter:04d}'
        case_id = question_to_case[question]

        # 为每个模型生成一条记录
        for model_info in models:
            # 从模型信息中提取 model 字段（模型服务标识）和 id（模型ID）
            model_name = model_info.get("model", "default")
            model_id = model_info.get("id", "")
            record = {
                "question": question,
                "answer": "",  # 空字符串，由推理服务填充
                "model": model_name,
                "case_id": case_id
            }
            # 填充 metainfo.infer_model_id
            if model_id:
                record["metainfo"] = {"infer_model_id": model_id}
            # 添加可选字段
            for field in OPTIONAL_FIELDS:
                value = extract_field_value(item, mapping, field)
                if value:
                    record[field] = value
            result.append(record)

    return result


def normalize_data(data: list, mapping: dict) -> list:
    """根据字段映射将数据转为标准格式

    映射格式：
    {
        "question": {"source_field": "question", "default": null},
        "answer": {"source_field": "answer", "default": null},
        "model": {"source_field": null, "default": "deepseek-r1"},
        "case_id": {"source_field": "id", "default": null}
    }

    处理规则：
    - 有 source_field 且源数据有该字段 → 使用源数据值
    - 无 source_field 或源数据无该字段 → 使用 default 值
    """
    # 提取字段配置
    def get_field_config(field_name):
        config = mapping.get(field_name, {})
        if isinstance(config, str):
            # 兼容旧格式：直接是字段名
            return {"source_field": config, "default": None}
        return config

    q_config = get_field_config('question')
    a_config = get_field_config('answer')
    m_config = get_field_config('model')
    c_config = get_field_config('case_id')

    q_field = q_config.get('source_field')
    a_field = a_config.get('source_field')

    if not q_field or not a_field:
        raise ValueError("字段映射必须包含 question 和 answer 的 source_field")

    # 可选字段配置
    opt_field_configs = {}
    for f in OPTIONAL_FIELDS:
        config = get_field_config(f)
        if config.get('source_field') or config.get('default'):
            opt_field_configs[f] = config

    result = []

    # case_id 分组生成
    question_to_case = {}
    case_counter = 0

    for idx, item in enumerate(data):
        # 获取原始值并检测空值
        q_raw = item.get(q_field)
        a_raw = item.get(a_field)

        if is_empty_value(q_raw):
            raise ValueError(f"第{idx+1}行 question 字段为空，无法标准化")
        if is_empty_value(a_raw):
            raise ValueError(f"第{idx+1}行 answer 字段为空，无法标准化")

        question = str(q_raw).strip()
        answer = str(a_raw).strip()

        # case_id 处理
        # 规则：有 source_field 用源数据值，无则自动生成（不使用 default）
        c_field = c_config.get('source_field')
        if c_field and item.get(c_field):
            case_id = str(item.get(c_field))
        else:
            # 无 case_id 字段，根据 question 分组自动生成
            if question not in question_to_case:
                case_counter += 1
                question_to_case[question] = f'case-{case_counter:04d}'
            case_id = question_to_case[question]

        # model 处理
        m_field = m_config.get('source_field')
        m_default = m_config.get('default')
        if m_field and m_field in item:
            model_value = str(item.get(m_field))
        elif m_default:
            model_value = str(m_default)
        else:
            model_value = 'default'

        record = {
            "question": question,
            "answer": answer,
            "model": model_value,
            "case_id": case_id
        }

        # 添加可选字段
        for std_field, config in opt_field_configs.items():
            src_field = config.get('source_field')
            default_val = config.get('default')
            if src_field and src_field in item:
                value = item.get(src_field)
                # 正确的空值检查：排除 None 和 NaN（pandas 读取 Excel 空单元格产生 NaN）
                if value is not None and not (isinstance(value, float) and math.isnan(value)):
                    if str(value).strip():
                        record[std_field] = str(value)
            elif default_val:
                record[std_field] = str(default_val)

        result.append(record)
    return result


def cmd_normalize(args):
    """将评测集转为标准格式"""
    load_result = load_data(args.input)
    if not load_result.get("success"):
        raise ValueError(f"数据加载失败: {load_result.get('message')}")
    data = load_result.get("data", {}).get("items", [])
    if not data:
        raise ValueError("评测集为空或无法解析")

    mapping_result = load_json(args.mapping)
    if not mapping_result.get("success"):
        raise ValueError(f"映射文件加载失败: {mapping_result.get('message')}")
    mapping = mapping_result.get("data", {})

    normalized = normalize_data(data, mapping)
    if not normalized:
        raise ValueError("转换后的评测集为空")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text('\n'.join(json.dumps(item, ensure_ascii=False) for item in normalized), encoding='utf-8')

    return {"success": True, "input_rows": len(data), "output_rows": len(normalized), "output_file": args.output}


def cmd_expand(args):
    """展开评测集（answer 为空场景）

    模型列表格式：
    {
        "models": [
            {"name": "...", "model": "...", "id": "..."},
            ...
        ],
        "mode": "single" | "multi"
    }
    """
    # 加载原始数据
    load_result = load_data(args.input)
    if not load_result.get("success"):
        raise ValueError(f"数据加载失败: {load_result.get('message')}")
    data = load_result.get("data", {}).get("items", [])
    if not data:
        raise ValueError("评测集为空或无法解析")

    # 加载映射配置
    mapping_result = load_json(args.mapping)
    if not mapping_result.get("success"):
        raise ValueError(f"映射文件加载失败: {mapping_result.get('message')}")
    mapping = mapping_result.get("data", {})

    # 加载用户选择的模型列表（新格式）
    models_result = load_json(args.models)
    if not models_result.get("success"):
        raise ValueError(f"模型列表文件加载失败: {models_result.get('message')}")
    models_data = models_result.get("data", {})
    models = models_data.get("models", [])
    if not models:
        raise ValueError("模型列表为空")

    # 展开数据
    expanded = expand_data(data, mapping, models)
    if not expanded:
        raise ValueError("展开后的评测集为空")

    # 输出 JSONL
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        '\n'.join(json.dumps(item, ensure_ascii=False) for item in expanded),
        encoding='utf-8'
    )

    # 返回模型服务标识列表（用于显示）
    model_names = [m.get("model", "default") for m in models]
    return {
        "success": True,
        "input_rows": len(data),
        "output_rows": len(expanded),
        "models": model_names,
        "output_file": args.output
    }


# ============================================================================
# 提交
# ============================================================================

def generate_evalset_id() -> str:
    """生成评测集ID"""
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"eval-{suffix}"


def cmd_submit(args):
    """提交评测集到后端服务

    metainfo 填充规则：
    - 如果提供了 --models 参数，根据 model 字段查找对应的 id
    - 填充 metainfo.infer_model_id 字段
    """
    # 加载模型列表（构建 model -> id 映射）
    model_id_map = {}
    if args.models:
        models_result = load_json(args.models)
        if models_result.get("success"):
            models_data = models_result.get("data", {})
            models_list = models_data.get("models", [])
            for m in models_list:
                model_key = m.get("model", "")
                model_id = m.get("id", "")
                if model_key and model_id:
                    model_id_map[model_key] = model_id

    # 解析评测集
    items = []
    for idx, line in enumerate(Path(args.evalset).read_text(encoding='utf-8').splitlines()):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            # 必填字段
            item = {
                "case_id": case.get('case_id', f'case-{idx+1:04d}'),
                "model": case.get('model', 'default'),
                "question": case['question'],
                "answer": case['answer']
            }
            # 必填字段非空检测（answer 可为空，由推理服务填充）
            for field in ['case_id', 'model', 'question']:
                if is_empty_value(item.get(field)):
                    raise ValueError(f"评测集第{idx+1}行 {field} 字段为空")
            # 可选字段（包含 metainfo，expand 阶段已填充）
            for field in OPTIONAL_FIELDS:
                if field in case and case[field]:
                    item[field] = case[field]
            # 兜底：若无 metainfo 且 model 有对应 id，则填充
            model_value = item.get('model', '')
            if 'metainfo' not in item and model_value in model_id_map:
                item['metainfo'] = {"infer_model_id": model_id_map[model_value]}
            items.append(item)
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"评测集第{idx+1}行解析失败: {e}")

    if not items:
        raise ValueError("评测集为空")

    # 提交到API
    config_result = load_config_kv(args.config)
    if not config_result.get("success"):
        raise ValueError(f"配置文件加载失败: {config_result.get('message')}")
    config = config_result.get("data", {})

    # 使用 TokenManager 和 ApiClient
    token_manager = TokenManager(args.auth)
    client = ApiClient(token_manager, config.get('base_url', 'http://127.0.0.1:8080'))

    evalset_id = generate_evalset_id()

    client.post("/open/api/v1/evalset", json={"evalset_id": evalset_id, "items": items})

    save_json(args.output, {"dataset": evalset_id, "total": len(items)})
    return {"evalset_id": evalset_id, "total": len(items)}


def analyze_field_with_mapping(data: list, mapping: dict, field_name: str) -> dict:
    """结合映射配置分析单个字段状态

    Args:
        data: 原始评测集数据列表
        mapping: 字段映射配置
        field_name: 标准字段名（answer/model/case_id）

    Returns:
        {"exists": bool, "source_field": str|null, "status": "all_empty"|"partial"|"all_filled"}
    """
    config = mapping.get(field_name, {})
    if isinstance(config, str):
        source_field = config
    else:
        source_field = config.get('source_field')

    if not source_field:
        return {"exists": False, "source_field": None, "status": "all_empty"}

    # 检查原始数据中该字段状态
    empty_count = 0
    for item in data:
        value = item.get(source_field)
        if is_empty_value(value):
            empty_count += 1

    total = len(data)
    if empty_count == total:
        status = "all_empty"
    elif empty_count == 0:
        status = "all_filled"
    else:
        status = "partial"

    return {"exists": True, "source_field": source_field, "status": status}


def cmd_check_status(args):
    """检查关键字段状态（结合映射配置）

    分析 answer、model、case_id 字段的填充状态，
    用于判断后续处理分支。
    """
    # 加载原始数据
    load_result = load_data(args.input)
    if not load_result.get("success"):
        raise ValueError(f"数据加载失败: {load_result.get('message')}")
    data = load_result.get("data", {}).get("items", [])
    if not data:
        raise ValueError("评测集为空或无法解析")

    # 加载映射配置
    mapping_result = load_json(args.mapping)
    if not mapping_result.get("success"):
        raise ValueError(f"映射文件加载失败: {mapping_result.get('message')}")
    mapping = mapping_result.get("data", {})

    # 分析关键字段状态
    result = {
        "answer": analyze_field_with_mapping(data, mapping, 'answer'),
        "model": analyze_field_with_mapping(data, mapping, 'model'),
        "case_id": analyze_field_with_mapping(data, mapping, 'case_id')
    }

    save_json(args.output, result)
    return {"status": result, "output": args.output}


# ============================================================================
# 批次提交（流式处理）
# ============================================================================

# D-36: 批次大小固定为 500 条
BATCH_SIZE = 500


def cmd_submit_batch(file_path: str, api_client, endpoint: str, models_path: str = None) -> dict:
    """
    分批提交评测集数据（流式处理）

    Args:
        file_path: JSONL 文件路径
        api_client: API 客户端实例
        endpoint: API 端点
        models_path: 模型列表文件路径（selected-models.json）

    Returns:
        包含 success, stats, errors 字段的结果字典

    实现决策:
        - D-36: 批次大小固定为 500 条
        - D-37: 批次采用顺序同步提交策略
        - D-38: 批次级别失败时立即停止处理
        - D-39: 单条数据错误收集在 errors 数组
        - D-40: 错误报告包含 line 和 message 字段
        - D-41: 进度输出到 stderr
        - D-42: 每批次完成后输出一次进度
        - D-43: 进度采用 JSON 格式
    """
    # 加载模型列表，构建 model -> id 映射
    model_id_map = {}
    if models_path:
        models_result = load_json(models_path)
        if models_result.get("success"):
            models_data = models_result.get("data", {})
            models_list = models_data.get("models", [])
            for m in models_list:
                model_key = m.get("model", "")
                model_id = m.get("id", "")
                if model_key and model_id:
                    model_id_map[model_key] = model_id

    # 1. 流式读取文件
    stream = load_jsonl_stream(file_path)

    # 2. 初始化状态
    batch = []
    stats = {"total": 0, "success": 0, "failed": 0, "batches": 0}
    errors = []
    evalset_id = generate_evalset_id()

    # 3. 流式处理
    for item in stream:
        # 3.1 处理错误项（单条数据错误）
        if item.get("success") is False:
            stats["total"] += 1
            stats["failed"] += 1
            # D-40: 错误报告包含 line 和 message 字段
            errors.append({
                "line": item.get("line", 0),
                "message": item.get("message", "未知错误")
            })
            continue

        # 3.2 构建数据项
        data = item["data"]
        record = {
            "case_id": data.get('case_id', f'case-{item["line"]:04d}'),
            "model": data.get('model', 'default'),
            "question": data['question'],
            "answer": data['answer']
        }
        # 必填字段非空检测（answer 可为空，由推理服务填充）
        for field in ['case_id', 'model', 'question']:
            if is_empty_value(record.get(field)):
                raise ValueError(f"评测集第{item['line']}行 {field} 字段为空")
        # 可选字段（包含 metainfo，expand 阶段已填充）
        for field in OPTIONAL_FIELDS:
            if field in data and data[field]:
                record[field] = data[field]
        # 兜底：若无 metainfo 且 model 有对应 id，则填充
        model_value = record.get('model', '')
        if 'metainfo' not in record and model_value in model_id_map:
            record['metainfo'] = {"infer_model_id": model_id_map[model_value]}

        batch.append(record)
        stats["total"] += 1

        # 3.3 批次满时提交
        if len(batch) >= BATCH_SIZE:
            try:
                api_client.post(endpoint, items=batch)
                stats["success"] += len(batch)
                stats["batches"] += 1
                # D-41, D-42, D-43: 进度输出到 stderr，JSON 格式
                print(json.dumps({"progress": stats["total"], "batches": stats["batches"]}), file=sys.stderr)
                batch = []
            except Exception as e:
                # D-38: 批次失败立即停止
                stats["failed"] += len(batch)
                error_msg = str(e)
                if hasattr(e, 'message'):
                    error_msg = e.message
                errors.append({"line": 0, "message": f"批次提交失败: {error_msg}"})
                return {
                    "success": False,
                    "code": getattr(e, 'code', ERR_REMOTE_DEFAULT),
                    "message": error_msg,
                    "stats": stats,
                    "errors": errors
                }

    # 4. 提交最后一批
    if batch:
        try:
            api_client.post(endpoint, items=batch)
            stats["success"] += len(batch)
            stats["batches"] += 1
            # D-41, D-42, D-43: 进度输出到 stderr
            print(json.dumps({"progress": stats["total"], "batches": stats["batches"]}), file=sys.stderr)
        except Exception as e:
            stats["failed"] += len(batch)
            error_msg = str(e)
            if hasattr(e, 'message'):
                error_msg = e.message
            errors.append({"line": 0, "message": f"批次提交失败: {error_msg}"})
            return {
                "success": False,
                "code": getattr(e, 'code', ERR_REMOTE_DEFAULT),
                "message": error_msg,
                "stats": stats,
                "errors": errors
            }

    # 5. 输出结果
    return {
        "success": True,
        "evalset_id": evalset_id,
        "stats": stats,
        "errors": errors
    }


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='评测集管理')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # analysis
    p = subparsers.add_parser('analysis', help='解析评测集结构')
    p.add_argument('--input', required=True, help='评测集文件路径')
    p.add_argument('--output', required=True, help='输出结构文件路径')
    p.set_defaults(func=cmd_analysis)

    # normalize
    p = subparsers.add_parser('normalize', help='标准化评测集')
    p.add_argument('--input', required=True, help='原始评测集文件路径')
    p.add_argument('--mapping', required=True, help='字段映射文件路径')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_normalize)

    # submit
    p = subparsers.add_parser('submit', help='提交评测集')
    p.add_argument('--evalset', required=True, help='标准化评测集文件路径')
    p.add_argument('--config', required=True, help='服务配置文件')
    p.add_argument('--auth', required=True, help='鉴权信息文件')
    p.add_argument('--models', required=False, help='模型列表文件路径（用于填充 metainfo）')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_submit)

    # expand
    p = subparsers.add_parser('expand', help='展开评测集（answer为空场景）')
    p.add_argument('--input', required=True, help='原始评测集文件路径')
    p.add_argument('--mapping', required=True, help='字段映射文件路径')
    p.add_argument('--models', required=True, help='用户选择的模型列表文件')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_expand)

    # check-status
    p = subparsers.add_parser('check-status', help='检查关键字段状态')
    p.add_argument('--input', required=True, help='原始评测集文件路径')
    p.add_argument('--mapping', required=True, help='字段映射文件路径')
    p.add_argument('--output', required=True, help='输出文件路径')
    p.set_defaults(func=cmd_check_status)

    args = parser.parse_args()

    # Python 3.6 兼容：手动检查子命令
    if args.command is None:
        parser.error("请指定子命令: analysis, normalize, expand, submit, check-status")

    try:
        result_obj = args.func(args)
        print(json.dumps(result_obj, ensure_ascii=False))
    except Exception as e:
        handle_cli_error(e)


if __name__ == '__main__':
    main()