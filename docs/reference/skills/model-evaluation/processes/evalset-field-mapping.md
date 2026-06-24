---
name: evalset-field-mapping
description: Use when evalset-parse reaches step 3 and needs to generate field mapping configuration
---

# 字段映射流程

读取评测集结构 → 匹配字段 → 生成映射配置 → 等待用户确认。

---

## 目标

生成字段映射配置 → 等待用户确认。

核心原则：**用户确认不可跳过，映射必须准确**。

---

## 触发条件

评测集解析流程检测到原始字段需映射为标准字段。

---

## 红线

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 确认映射缺失时保存配置 | 用户未确认即保存，可能导致错误映射 | 必须等待用户确认后才保存 |
| 用户未回复时自动继续 | 跳过用户交互，违反流程规范 | 等待用户回复后继续 |
| 认为"映射看起来正确，无需确认" | 凭直觉判断，忽视用户确认要求 | 所有映射必须经用户确认 |

---

## 步骤1：生成映射

**目的**：根据评测集原始字段生成标准字段映射配置。

| 状态 | 动作 |
|------|------|
| 结构文件存在 | → 读取字段列表 |
| 字段匹配成功 | → 生成映射配置 |
| 字段匹配失败 | → 提示用户手动指定 |

### 字段匹配规则

| 标准字段 | 关键词 | 匹配规则 |
|----------|--------|----------|
| question | question, prompt, input, query, 问题, 提问 | 精确优先，包含次之 |
| answer | answer, response, output, reply, 回答, 回复 | 精确优先，包含次之 |
| model | model, model_name, model_id, llm, llm_name, 模型, 模型名称 | 精确优先，包含次之 |
| case_id | case_id, caseid, 用例id | **仅精确匹配** |
| reference | reference, ref, gold, 参考答案, 标准答案 | 精确优先，包含次之 |
| keypoint | keypoint, keypoints, 关键点, 评测点 | 精确优先，包含次之 |

> 其他字段（system, context, category）见 `references/字段映射详表.md`

**必填字段**：question、answer、model、case_id

**映射格式**：

```json
{
  "question": {"source_field": "问题", "default": null},
  "answer": {"source_field": "回答", "default": null},
  "model": {"source_field": "模型名称", "default": null},
  "case_id": {"source_field": "id", "default": null}
}
```

---

## 步骤2：确认映射配置 ⚠️

**目的**：确保字段映射准确，避免后续处理错误。

展示映射表（含标准字段含义），询问："以上映射是否正确？(Y/n)"

**此步骤必须等待用户确认，不可跳过。**

| 用户选择 | 动作 |
|------|------|
| Y | → 保存映射，返回主流程 |
| n | → 调整映射，重新确认 |

> **注意**：如果评测集由 AI 助手生成，跳过此确认步骤。

---

## 返回点

返回调用该流程处

---

## 产物

| 文件 | 用途 |
|------|------|
| `{work-dir}/.eval/{session-id}/evalset/evalset-fields-mapping.json` | 字段映射配置，供标准化流程使用 |

---

## 变量速查

| 变量 | 说明 |
|------|------|
| `{work-dir}` | 当前工作目录 |
| `{session-id}` | 会话目录名，格式 `session-{8位字母数字}` |
| `{skill-dir}` | 技能安装目录 |