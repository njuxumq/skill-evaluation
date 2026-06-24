"""Forbidden terms and patterns extracted from SKILL.md constraints."""
import re

# Terms unique enough for exact substring match (won't appear in normal prose)
FORBIDDEN_TERMS_EXACT: list[str] = [
    "TokenPlan",
    "EvalPlan",
    "limited_free",
    "recommend_model_id",
    "dataset-id",
    "task-id",
]

# Common words that only indicate leakage in API-like context (JSON keys, quotes, dot-access)
FORBIDDEN_TERMS_CONTEXTUAL: list[re.Pattern[str]] = [
    re.compile(r'["\']candidate["\']|"candidate"\s*:'),
    re.compile(r'["\']judge["\']|"judge"\s*:'),
    re.compile(r'["\']usage["\']|"usage"\s*:|\.usage\b'),
    re.compile(r'["\']source["\']|"source"\s*:|\.source\b'),
]

# Full list for lint (substring matching in restricted-scope docs)
FORBIDDEN_TERMS: list[str] = [
    "TokenPlan",
    "EvalPlan",
    "limited_free",
    "candidate",
    "judge",
    "usage",
    "source",
    "recommend_model_id",
    "dataset-id",
    "task-id",
]

FORBIDDEN_PATTERNS: list[str] = [
    r"正在(检查|加载|读取|上传|执行|搜索|打包)",
    r"现在(进入|读取|检查|执行)",
    r"接下来(我|需要|进入|执行)",
    r"(已|已经)(识别|确认|检测|加载)",
    r"(从|根据).{2,20}(提取|识别|推断)出",
    r"(进入|跳转到|跳过).{0,10}(阶段|流程|步骤|分支)",
    r"(用户|你)(说的是|描述的是|的意图是|想要的是)",
    r"Token\s*(检查|有效|通过|失效)",
    r"鉴权(完成|通过|成功)",
    r"(无|没有)(历史|最近)任务",
]

FIXED_TODOWRITE_CONTENTS: list[str] = [
    "确认评测场景",
    "配置评测对象",
    "准备评测数据",
    "提交并查看报告",
]
