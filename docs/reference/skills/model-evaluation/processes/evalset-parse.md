---
name: evalset-parse
description: Use when eval-build reaches evalset parsing step, or user directly requests parsing an evaluation dataset
---

# 评测集解析流程

本文档定义评测集解析流程，将用户评测集解析为标准格式，检测答案状态后调用相应子流程处理。

## 目标

解析评测集 → 检测状态 → 调用子流程 → 返回标准化阶段。

核心原则：**步骤顺序执行，检测结果决定子流程**。

---

## 触发条件

评测集处理阶段需要解析评测集，或用户直接请求解析评测集文件。

---

## 流程速查

| 编号 | 流程名称 | 文档位置 | 调用时机 |
|------|----------|----------|----------|
| 流程3.1 | 标准字段映射 | [evalset-field-mapping.md](./evalset-field-mapping.md) | 步骤3 |
| 流程3.2 | 推理模型选择 | [evalset-model-selection.md](./evalset-model-selection.md) | 步骤4检测结果为空 |
| 流程3.3 | 标准字段校验 | [evalset-field-validation.md](./evalset-field-validation.md) | 步骤4检测结果为非空 |

---

## 红线

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 未执行 check-status 就选择流程 | 凭直觉判断状态 | 必须执行脚本检测，读取 evalset-status.json |
| 用户未回复时自动继续 | 交互被跳过 | 步骤3、partial 处理必须等待用户确认 |
| 字段映射未确认就保存 | 流程3.1 确认被跳过 | 确认步骤标注 ⚠️，必须等待用户回复 |
| 评测集文件格式不支持 | 非 jsonl/csv/xlsx | 提示用户转换为支持的格式 |

---

## 步骤1：获取评测集文件

**目的**：确保评测集文件就位。

| 状态 | 动作 |
|------|------|
| `evalset-prepared.{ext}` 已存在 | → 步骤2 |
| 不存在 | 获取用户文件 |

获取方式：复制用户文件或远程下载至 `{work-dir}/.eval/{session-id}/evalset/`。

---

## 步骤2：解析字段结构

**目的**：识别评测集的字段组成，为字段映射提供依据。

| 状态 | 动作 |
|------|------|
| `evalset-structure.json` 已存在 | → 步骤3 |
| 不存在 | 执行下方命令 |

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_set.py analysis \
  --input {work-dir}/.eval/{session-id}/evalset/evalset-prepared.{ext} \
  --output {work-dir}/.eval/{session-id}/evalset/evalset-structure.json
```

输出字段：`file`, `format`, `total_rows`, `fields`。

---

## 步骤3：生成字段映射

**目的**：建立原始字段与标准字段的对应关系。

| 状态 | 动作 |
|------|------|
| `evalset-fields-mapping.json` 已存在 | → 步骤4 |
| 不存在 | 执行流程3.1 |

执行 **流程3.1** 完成字段映射生成与确认。

---

## 步骤4：检测评测集状态

**目的**：判断 answer 字段状态，决定后续处理流程。

**必须执行脚本检测**，不得凭直觉判断。

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_set.py check-status \
  --input {work-dir}/.eval/{session-id}/evalset/evalset-prepared.{ext} \
  --mapping {work-dir}/.eval/{session-id}/evalset/evalset-fields-mapping.json \
  --output {work-dir}/.eval/{session-id}/evalset/evalset-status.json
```

读取 `evalset-status.json` 中 `answer.status`：

| status | 后续流程 | 返回点
|--------|----------|----------|
| `all_empty` | → 流程3.2 |  返回标准化阶段   |
| `all_filled` | → 流程3.3 |  返回标准化阶段  |
| `partial` | 询问用户 |

**partial 处理**：询问用户视为"只有问题"或"问题+答案"。

---

## 返回点

流程结束后，返回评测集处理阶段的任务1步骤2。

---

## 产物

| 文件 | 用途 |
|------|------|
| `evalset-structure.json` | 字段结构分析 |
| `evalset-fields-mapping.json` | 字段映射配置 |
| `evalset-status.json` | 状态检测结果 |
| `selected-models.json` | 模型列表（流程3.2产出） |

---

## 变量速查

见 [SKILL.md 变量速查](../SKILL.md#变量速查)。