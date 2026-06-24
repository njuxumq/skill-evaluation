# CLAUDE.md

## 项目定位

本项目是 **skill-evaluation 技能的开发工作区**，用于迭代完善与优化这个 Claude Code Skill。

产品是 `.claude/skills/skill-evaluation/` 目录下的全部文件——Skill 文档（控制 Claude 运行时行为）+ Python 脚本（封装后端 API）。`docs/reference/` 是设计知识库，指导 Skill 的设计决策。

## 目录结构

```
skill-evaluation/
├── CLAUDE.md                           # 本文件（开发指南）
├── .claude/skills/skill-evaluation/    # 产品：Skill 本体
│   ├── SKILL.md                        # 入口 + 全局规范（最重要）
│   ├── eval-init.md                    # 阶段1：初始化
│   ├── eval-build.md                   # 阶段2：配置评测对象
│   ├── eval-set.md                     # 阶段3：数据准备
│   ├── eval-execute.md                 # 阶段4：提交与报告
│   ├── processes/                      # 子流程（被阶段文档引用）
│   ├── references/                     # 运行时参考（脚本定义、字段说明、模板）
│   └── scripts/                        # Python 实现（含 eval_skill.py 入口脚本）
│       ├── eval_skill.py               # CLI 入口脚本
│       └── cfg/                        # 服务配置（eval-server.cfg、eval-auth.cfg）
└── docs/reference/                     # 知识库：Skill 设计方法论
    ├── Writing-Skills规范.md            # Skill 编写规范总纲
    ├── Agent-Skill-五种设计模式.md       # 五种模式（本 Skill 用 Pipeline）
    ├── Claude-Code-Skills-实战经验.md    # Anthropic 九种 Skill 类型
    ├── Claude-Skills-完全构建指南.md     # 官方构建指南
    └── Harness-Design-阅读报告.md       # 长任务 Harness 设计参考
```

## 设计模式

本 Skill 采用 **Pipeline（流水线）模式** —— 强制执行带检查点的严格多步骤工作流：

```
阶段1（初始化） → 阶段2（配置） → 阶段3（数据） → 阶段4（执行）
```

每个阶段文档定义：目标 → 完成标志 → 任务列表 → Red Flags → 常见错误。子流程通过 `processes/` 下的独立文档承载复杂交互逻辑。

**文档分层设计**（递进式披露）：

| 层级 | 文件 | 加载时机 |
|------|------|----------|
| L1 | SKILL.md frontmatter | 始终在上下文 |
| L2 | SKILL.md 正文 + 阶段文档 | Skill 触发时 |
| L3 | processes/ + references/ | 执行到具体步骤时按需加载 |

## 核心不变量

修改 Skill 时，以下约束绝不能破坏：

### 输出约束

- 所有面向用户的输出必须**中文**
- 禁止暴露内部实现（脚本命令、JSON 字段、内部 ID、执行流转逻辑）
- 禁止输出思考过程、推理结论、状态描述
- 只允许输出：选项表、单行提问、确认问句、登录提示、结果摘要
- 判断标准：「这句话是在直接向用户提问/请用户选择/展示最终结果吗？不是 → 不输出」

### 交互约束

- 禁止使用 `AskUserQuestion` 工具，所有交互通过文本 + Markdown 编号表格
- TodoWrite content 固定为 4 个阶段名称（确认评测场景/配置评测对象/准备评测数据/提交并查看报告）
- 驱动模型列表禁止标注「推荐」，必须按 display_name 字母排序
- 评委模型必须排除已选驱动模型后再推荐

### 执行约束

- 静默执行原则：鉴权、搜索、打包、上传、轮询等操作全程静默
- 自动填充规则：进入新步骤前必须先检查上下文是否已有所需输入
- 命令不可猜测：必须以文档明确写出的命令为准，禁止凭记忆构造

### 术语约束

| 用户可见 | 禁止暴露 |
|----------|----------|
| 云端模型、自定义模型 | `TokenPlan`、`EvalPlan`、`limited_free` |
| 驱动模型、评委模型 | `candidate`、`judge`、`usage`、`source` |
| Skill 名称、显示名称 | `recommend_model_id`、`dataset-id`、`task-id` |

## 文档依赖图

修改任一文件时，必须检查并同步相关文件：

```
SKILL.md（全局规范）
  ├─→ eval-init.md ─→ processes/scene-detection.md
  ├─→ eval-build.md ─→ processes/skill-selection.md
  │                  ─→ processes/model-selection.md
  ├─→ eval-set.md ─→ processes/dataset-prepare.md
  │               ─→ processes/dataset-preview.md
  ├─→ eval-execute.md
  └─→ references/（被所有阶段文档引用）
       ├── 脚本定义.md        ← 新增/修改子命令时必须同步
       ├── 中间产物说明.md     ← 修改文件字段时必须同步
       ├── 评测场景说明.md     ← 修改场景逻辑时必须同步
       └── 进度展示规范.md     ← 修改 TodoWrite/表格格式时必须同步
```

**高频同步场景**：

| 修改内容 | 必须同步的文件 |
|----------|---------------|
| 新增/修改 eval_skill.py 子命令 | `references/脚本定义.md` + 调用该命令的阶段文档 |
| 修改评测场景定义 | `references/评测场景说明.md` + `processes/scene-detection.md` + `eval-build.md`（数量决策表） |
| 修改 activeForm 步骤描述 | `SKILL.md` 对照表 + `references/进度展示规范.md` |
| 修改中间文件字段 | `references/中间产物说明.md` + 读写该文件的阶段文档 |
| 修改用户交互措辞 | 对应阶段文档 + `SKILL.md` Red Flags 表（若涉及新违规模式） |

## 修改指南

### 优化交互措辞

定位到对应阶段文档中的步骤，直接修改展示格式。检查 `SKILL.md` 的 Red Flags 表是否需要新增对应违规条目。

### 新增评测场景

1. `references/评测场景说明.md` 添加场景定义
2. `processes/scene-detection.md` 更新选项表和信号识别规则
3. `eval-build.md` 更新各任务的「数量决策」表
4. `SKILL.md` 中场景选择表是否需要扩展

### 新增 eval_skill.py 子命令

1. 在 `eval_skill.py` 中实现子命令
2. `references/脚本定义.md` 添加完整命令文档
3. 在调用该命令的阶段文档中写明调用方式
4. 若产生新文件 → 更新 `references/中间产物说明.md`

### 调整阶段流程

1. 修改对应阶段文档的任务列表和完成标志
2. 检查上下游阶段的前置验证是否受影响
3. 更新 `SKILL.md` 中的阶段进度对照表
4. 更新 `references/进度展示规范.md`

## 验证方法

Skill 文档修改后无法通过自动化测试验证，需通过以下方式判断正确性：

1. **一致性检查**：文档间的交叉引用是否匹配（场景名称、命令格式、字段名）
2. **完整性检查**：每个分支是否有明确的后续动作、每个步骤是否有对应的 activeForm
3. **约束合规**：新增的用户可见输出是否符合「核心不变量」中的所有约束
4. **Red Flags 覆盖**：新增的交互模式是否有可能被误用，是否需要新增 Red Flag 条目
5. **模拟走查**：以用户身份模拟触发 Skill，逐步检查 Claude 应产生的行为是否符合文档描述

## 参考知识库

`docs/reference/` 下的文档是设计决策的理论依据：

| 文档 | 用途 |
|------|------|
| Writing-Skills规范.md | Skill 编写的总纲性规范，评审 Skill 质量时参考 |
| Agent-Skill-五种设计模式.md | 本 Skill 采用 Pipeline 模式，理解模式特征和约束 |
| Claude-Code-Skills-实战经验.md | Anthropic 官方九种 Skill 类型分类，定位本 Skill 属于「业务流程自动化」类 |
| Claude-Skills-完全构建指南.md | 官方构建指南，涵盖结构、测试、分发全流程 |
| Harness-Design-阅读报告.md | 长任务 Agent 设计参考（上下文重置、GAN 式评估等） |

**何时查阅**：当需要做架构级调整（如拆分阶段、改变交互模式、引入新的设计模式）时，先阅读相关参考文档再做决策。
