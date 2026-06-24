#!/usr/bin/env python3
"""mock_eval_skill.py — 根据子命令从 fixture 文件返回预设响应。

支持两种 fixture 格式：
- Object（静态）：每次调用返回相同 JSON
- Array（序列）：按调用顺序依次返回，最后一个元素永久重复

被拷贝到测试 workspace 中替换真实 eval_skill.py。
仅使用 stdlib，无外部依赖。
"""
import sys
import json
from pathlib import Path


def find_work_dir(args: list) -> Path:
    """从命令行参数中提取 work-dir。"""
    for i, arg in enumerate(args):
        if arg == "--work-dir" and i + 1 < len(args):
            return Path(args[i + 1])
        if arg == "--auth-file" and i + 1 < len(args):
            return Path(args[i + 1]).parent.parent
    return Path.cwd()


def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"status": "error", "message": "no subcommand"}))
        return

    subcommand = args[0]
    work_dir = find_work_dir(args)
    fixture_path = work_dir / ".eval-fixtures" / f"{subcommand}.json"

    if not fixture_path.exists():
        print(json.dumps({"status": "ok"}))
        return

    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        response = data[0]
        remaining = data[1:] if len(data) > 1 else data
        fixture_path.write_text(
            json.dumps(remaining, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(response, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
