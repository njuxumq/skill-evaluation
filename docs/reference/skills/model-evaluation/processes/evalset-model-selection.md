---
name: evalset-model-selection
description: Use when evalset-parse determines answer field is empty and needs model selection
---

# 推理模型选择流程

获取可用推理模型列表，用户分类选择并保存，返回标准化阶段。

---

## 目标

获取可用模型列表 → 用户分类选择 → 累积保存 → 返回标准化阶段。

核心原则：**分类展示、累积选择、用户确认后保存**。

---

## 触发条件

answer 字段不存在或全空。

---

## 红线

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 未等待用户确认直接保存 | 跳过交互确认环节 | 必须等待用户确认后才调用保存脚本 |
| Token 失效时继续执行 | 授权已过期，API调用失败 | 引导用户重新授权 |
| 模型列表获取失败 | 网络问题或服务不可用 | 检查网络连接，重试或联系管理员 |
| 单页展示超过3个模型 | AskUserQuestion 选项限制 | 严格执行每页最多3模型 + 1操作选项 |
| 跳过已选列表确认 | 用户无法看到最终选择结果 | 所有厂商完成后必须展示已选列表确认 |
| 未使用多选模式 | 用户每轮只能选1个模型 | 设置 `multiSelect: true` |

---

## 步骤1：获取可用模型列表

**目的**：获取评测服务支持的推理模型详情列表。

| 状态 | 动作 |
|------|------|
| 获取成功 | → 进入步骤2 |
| Token 失效 | → 引导重新授权 |
| 网络失败 | → 检查连接后重试 |

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_model.py list-models \
  --auth {work-dir}/.eval/auth.json \
  --config {skill-dir}/scripts/cfg/eval-server.cfg \
  --output {work-dir}/.eval/{session-id}/available-models.json
```

---

## 步骤2：用户分类选择模型

⚠️ **此步骤需要用户交互确认**：用户需浏览模型列表、选择模型、确认后才能保存。

### 步骤2.1：按厂商分组

读取 `available-models.json`，按厂商分组（DeepSeek、Qwen、讯飞星火、测试模型等）。

识别规则：按模型 `name` 或 `model` 字段关键词识别厂商。

| 厂商 | 识别关键词 |
|------|------------|
| DeepSeek | `deepseek` |
| Qwen | `qwen`, `op3` |
| 讯飞星火 | `spark`, `星火` |
| 测试模型 | `test` 或其他未匹配 |

### 步骤2.2：分厂商多选

使用 AskUserQuestion 工具（multiSelect: true），按厂商逐批展示，用户每批可多选模型。

**选项构成**：

| 位置 | 类型 | 格式 |
|------|------|------|
| 选项1-2 | 模型 | `{name}` |
| 选项3 | 操作 | `下一页`（厂商内模型超过2个时显示） |
| 选项4 | 操作 | `结束选择`（用户可随时结束，不再展示后续厂商） |

**交互规则**：

| 规则 | 说明 |
|------|------|
| 多选模式 | `multiSelect: true`，用户一次可选多个模型 |
| 分组依据 | 按厂商分类展示（DeepSeek、Qwen、讯飞星火等） |
| 分页规则 | 每页最多2个模型 + 下一页 + 结束选择 |
| 厂商切换 | 用户未选择"结束选择"时，当前厂商选完后自动进入下一厂商 |
| 结束条件 | 用户选择"结束选择"或所有厂商完成，展示已选列表确认 |

**交互流程**：

1. 展示厂商1（多选模式，含"下一页"和"结束选择"选项）
2. 用户选择模型 + "结束选择" → 直接进入已选列表确认
3. 用户选择模型 + "下一页" → 展示当前厂商下一页
4. 用户仅选择模型（未选操作） → 进入下一厂商
5. 所有厂商完成 → 展示已选列表确认

**AskUserQuestion 标题格式**：
- `选择 {厂商名} 系列模型（可多选）`

### 步骤2.3：确认已选列表

所有厂商选择完成后，展示已选模型列表让用户确认：

| 用户操作 | 动作 |
|----------|------|
| 确认保存 | → 进入步骤2.4保存 |
| 重新选择 | → 清空已选列表，重新开始步骤2.2 |

**展示格式**：
```
已选模型：DeepSeek-V3.1, Qwen3-235B, 星火角色扮演
共3个模型，是否确认保存？
```

### 步骤2.4：保存已选列表

用户点击"确认保存"后，调用脚本保存：

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_model.py select-models \
  --input {work-dir}/.eval/{session-id}/available-models.json \
  --selection "{已选模型model字段值，逗号分隔}" \
  --output {work-dir}/.eval/{session-id}/selected-models.json
```

**示例**：已选 DeepSeek-V3.1 和 Qwen3-235B，`--selection` 参数为 `xdeepseekv31,xop3qwen235b`。

---

## 步骤3：保存选择结果

**目的**：将用户确认的模型列表保存到文件。

| 状态 | 动作 |
|------|------|
| 保存成功 | → 返回标准化阶段 |
| 保存失败 | → 检查参数后重试 |

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_model.py select-models \
  --input {work-dir}/.eval/{session-id}/available-models.json \
  --selection "{用户确认的模型序号或名称}" \
  --output {work-dir}/.eval/{session-id}/selected-models.json
```

**`--selection` 参数格式**：

| 格式 | 示例 |
|------|------|
| 序号选择 | `1` 或 `1,3` |
| 模型名称 | `deepseek-chat` 或 `deepseek-chat,spark-lite` |

---

## 返回点

返回调用该流程处

---

## 产物

| 文件 | 用途 |
|------|------|
| `available-models.json` | 可用模型列表缓存 |
| `selected-models.json` | 用户选择的推理模型列表 |

---

## 变量速查

通用变量见 [SKILL.md 变量速查](../SKILL.md#变量速查)。

---