# ✅ init_01_fresh_no_history

| 项目 | 值 |
|------|-----|
| 用例名 | 全新用户首次触发，无历史任务 |
| 裁决 | **PASS** |
| 模型 | `xopglm51` |
| 耗时 | 90.7s |
| 优先级 | P0 |
| 阶段 | init |

> **期望**: 无历史任务时，展示自然语言引导（含 xxx Skill 占位符），不展示历史任务表。

---

## 1. 断言裁决

共 9 条断言，✅ 9 通过

### 通用规则

| 规则 | 描述 | 结果 | 详情 |
|------|------|:----:|------|
| H1 | 首个动作是进度管理工具 | ✅ |  |
| H2 | 进度工具之前无文本输出 | ✅ |  |
| H3 | 进度内容为4个固定阶段名 | ✅ |  |
| H4 | 无禁用术语泄露 | ✅ |  |
| H5 | 无内部ID/字段泄露 | ✅ |  |
| H6 | 输出语言为中文 | ✅ |  |
| H9 | 引导含 xxx Skill 占位符 | ✅ |  |

### 自定义断言

| 描述 | 结果 | 详情 |
|------|:----:|------|
| 🤖 语义含 "引导用户描述评测需求" | ✅ | ⚠ judge skipped: "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted" |
| 输出不含 "最近的评测任务" | ✅ |  |

---

## 2. Claude 输出

#### Turn 0 (指令: "skill-evaluation")

```text
请描述你的评测需求，例如：「评测 xxx Skill 的效果」「对比 claude-sonnet-4-6 和 claude-opus-4-7 驱动同一 Skill 的表现」。
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

**指令**: `skill-evaluation`

**预期行为**:

> 无历史任务时，展示自然语言引导（含 xxx Skill 占位符），不展示历史任务表。

**Fixtures**:

- `check-token`: `{"status": "valid", "expires_at": "2026-07-01T00:00:00Z"}`
- `recent-tasks`: `{"tasks": []}`

</details>
