# ❌ init_02_has_history_no_intent

| 项目 | 值 |
|------|-----|
| 用例名 | 有历史任务但用户未描述具体需求 |
| 裁决 | **FAIL** |
| 模型 | `xopglm51` |
| 耗时 | 108.1s |
| 优先级 | P0 |
| 阶段 | init |

> **期望**: 有历史任务时必须先展示历史任务表（Markdown 表格），同时提供"新建"入口。

---

## 1. 断言裁决

共 11 条断言，✅ 10 通过，❌ 1 失败

| # | 规则 | 描述 | 结果 | 详情 |
|--:|------|------|:----:|------|
| 1 | H1 | 首个动作是进度管理工具 | ✅ |  |
| 2 | H2 | 进度工具之前无文本输出 | ✅ |  |
| 3 | H3 | 进度内容为4个固定阶段名 | ✅ |  |
| 4 | H4 | 无禁用术语泄露 | ✅ |  |
| 5 | H5 | 无内部ID/字段泄露 | ✅ |  |
| 6 | H6 | 禁止使用 AskUserQuestion | ✅ |  |
| 7 | H7 | 选项使用Markdown表格 | ✅ |  |
| 8 | semantic_match | 🤖 语义含 "向用户展示了历史评测任务列表" | ✅ | ⚠ judge skipped: "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted" |
| 9 | text_present | 输出含 "新建" | ❌ | Expected text not found: '新建' |
| 10 | text_absent | 输出不含 "eval-3g5k9m" | ✅ |  |
| 11 | format_check:markdown_table | 格式: markdown_table | ✅ |  |

---

## 2. Claude 输出

#### Turn 0 (指令: "评测 skill")

```text
| # | 历史任务 | Skill | 驱动模型 | 状态 | 进度 | 提交时间 |
|---|---------|-------|----------|------|------|----------|
| 1 | test-skill | test-skill | GLM-5 | 已完成 | 100% | 2026-06-08 |

你可以选择继续历史任务，或开始新的评测。请描述你的评测需求，例如：「评测 xxx Skill 的效果」、「对比 A 和 B 两个 Skill」、「用不同模型驱动同一个 Skill」等。
```

---

## 3. 执行轨迹

| # | 工具 | 关键参数 |
|--:|------|----------|
| 1 | `TaskCreate` | "确认评测场景" |
| 2 | `TaskCreate` | "配置评测对象" |
| 3 | `TaskCreate` | "准备评测数据" |
| 4 | `TaskCreate` | "提交并查看报告" |
| 5 | `TaskUpdate` | taskId: 1, status: in_progress |
| 6 | `Read` | ...mqxu11/.claude/skills/skill-evaluation/references/脚本定义.md |
| 7 | `Bash` | `python3 "/home/mqxu11/projects/claude/skill-evaluation/eval/results/v0.1/work...` |
| 8 | `Bash` | `python3 "/home/mqxu11/projects/claude/skill-evaluation/eval/results/v0.1/work...` |
| 9 | `TaskUpdate` | taskId: 1, status: 分析评测需求 |

---

<details>
<summary><strong>4. 用例设计（展开查看）</strong></summary>

**指令**: `评测 skill`

**预期行为**:

> 有历史任务时必须先展示历史任务表（Markdown 表格），同时提供"新建"入口。
> 不得暴露内部 task_id。

**Fixtures**:

- `check-token`: `{"status": "valid", "expires_at": "2026-07-01T00:00:00Z"}`
- `recent-tasks`: `{"tasks": [{"session_id": "20260608_100000_abc", "skill_name": "test-skill", "model": "GLM-5", "s...`

</details>
