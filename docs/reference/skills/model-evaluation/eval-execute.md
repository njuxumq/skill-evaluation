---
name: eval-execute
description: Use when build phase completed and ready to submit or check evaluation tasks
---

# 评测执行阶段

## 目标

完成任务提交、状态监控、结果展示后，评测流程结束。

核心原则：**轮询优先，状态驱动，错误可追溯**。

**前置验证**：`auth.json` 存在、`eval-dimension.json` 存在、`eval-judge.json` 存在、`evalset-meta.json` 存在。缺失则返回对应前置阶段。

## 何时使用

- 评测集处理阶段已完成（维度、评测集、评委配置就绪）
- 需要提交、查询或展示评测任务时

---

## 阶段完成标志

**验证顺序**（按序执行，任一失败则执行对应任务）：

1. ✅ 检查 `{work-dir}/.eval/{session-id}/evaltask/evaltask-meta.json` 存在 → 否则执行任务1
2. ✅ 检查任务状态为 `Succeeded` 或 `Failed` → 否则执行任务2
3. ✅ 评测结果已展示给用户 → 否则执行任务3

全部通过后，评测流程结束。

---

## 任务列表

### 任务1：提交评测任务

执行任务时展示：

> **当前任务：提交评测任务**
> 校验配置完整性 → 提交至评测服务 → 获取任务ID

**执行流程**（脚本自动执行）：

1. **填充 judge_id**：将评委配置中的 `id` 填充到所有主观评测维度
2. **校验配置**：检查维度配置完整性（必填字段、权重总和等）
3. **提交任务**：将任务提交至远程评测服务

**判断**：`{work-dir}/.eval/{session-id}/selected-models.json` 是否存在？

| 状态 | 动作 |
|------|------|
| 存在 | 评测集无答案场景，添加 `--inference_models` 参数 |
| 不存在 | 评测集有答案场景，使用原命令 |

---

**提交命令**：

**有推理配置**（评测集无答案场景）：
```bash
{python-env}{python-cmd} "{skill-dir}/scripts/eval_task.py" submit \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --auth "{work-dir}/.eval/auth.json" \
  --eval_set "{work-dir}/.eval/{session-id}/evalset/evalset-meta.json" \
  --eval_dimension "{work-dir}/.eval/{session-id}/eval-dimension.json" \
  --eval_judge "{work-dir}/.eval/{session-id}/eval-judge.json" \
  --inference_models "{work-dir}/.eval/{session-id}/selected-models.json" \
  --output "{work-dir}/.eval/{session-id}/evaltask/evaltask-meta.json"
```

**无推理配置**（评测集有答案场景）：
```bash
{python-env}{python-cmd} "{skill-dir}/scripts/eval_task.py" submit \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --auth "{work-dir}/.eval/auth.json" \
  --eval_set "{work-dir}/.eval/{session-id}/evalset/evalset-meta.json" \
  --eval_dimension "{work-dir}/.eval/{session-id}/eval-dimension.json" \
  --eval_judge "{work-dir}/.eval/{session-id}/eval-judge.json" \
  --output "{work-dir}/.eval/{session-id}/evaltask/evaltask-meta.json"
```

**失败处理**：参考 [评测服务接口说明.md](./references/评测服务接口说明.md#错误码) 进行排查。

---

### 任务2：查询任务状态

执行任务时展示：

> **当前任务：查询任务状态**
> 轮询任务状态 → 等待执行完成 → 下载评测报告

#### 执行方式

| 方式 | 说明 |
|------|------|
| 后台轮询（默认） | 使用 Bash 后台模式执行轮询，用户可继续其他工作，完成后自动通知主代理 |
| 前台轮询 | 阻塞等待，实时展示状态（用户要求时使用） |
| 单次查询 | 立即返回当前状态（仅需检查状态时使用） |

#### 后台轮询（默认）

使用 Bash 工具执行轮询命令，设置 `run_in_background: true`，继承主会话权限。

> **注意**：不使用 Agent 工具启动子代理，因为子代理无法继承主会话的权限配置，会导致执行失败。

**步骤1**：启动后台任务

使用 Bash 工具执行以下命令，设置 `run_in_background: true`：

```bash
{python-env}{python-cmd} "{skill-dir}/scripts/eval_task.py" status \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --auth "{work-dir}/.eval/auth.json" \
  --evaltask "{work-dir}/.eval/{session-id}/evaltask/evaltask-meta.json" \
  --output "{work-dir}/.eval/{session-id}/evaltask/evaltask-result.json" \
  --poll --interval 30 --timeout 3600
```

**Bash 工具参数**：
- `run_in_background: true` - 后台执行
- `timeout: 600000` - 超时时间（毫秒）

**步骤2**：提示用户

> 评测任务正在后台执行，您可以继续其他工作。任务完成后会自动通知您。

**步骤3**：处理结果

后台任务完成后，主代理收到通知，执行以下操作：

1. **读取后台任务输出文件**（`{task-output-file}`）
2. **提取关键信息**：从输出最后一行 JSON 中提取 `platform_url`（在线报告链接）
3. **根据状态执行动作**：

| 状态 | 动作 |
|------|------|
| Succeeded | 输出变量`{platform_url}`，进入任务3 |
| Failed | 展示错误信息 |
| Cancelled | 询问用户后续操作 |

#### 其他方式

**前台轮询**：用户要求实时观察进度时使用，直接执行轮询命令（不启动子代理）。

**单次查询**：仅需检查当前状态时使用，移除 `--poll` 参数。

#### 状态说明

| 状态 | 说明 | 动作 |
|------|------|------|
| Pending | 任务已创建，等待执行 | 继续等待 |
| Running | 任务正在执行 | 继续等待 |
| Succeeded | 任务执行成功 | 进入任务3 |
| Failed | 任务执行失败 | 展示错误信息 |
| Cancelled | 任务被取消 | 询问用户后续操作 |

#### 失败处理

参考 [评测服务接口说明.md](./references/评测服务接口说明.md#错误码) 进行排查。

---

### 任务3：展示评测结果

执行任务时展示：

> **当前任务：展示评测结果**
> 解析评测结果 → 展示得分摘要 → 提供在线报告链接

**目标**：将评测结果摘要展示给用户，并提供在线查看链接。

**结果展示命令**：

```bash
{python-env}{python-cmd} "{skill-dir}/scripts/eval_task.py" summary \
  --result "{work-dir}/.eval/{session-id}/evaltask/evaltask-result.json" \
  --platform_url "{platform_url}"
```

**输出内容**：

1. **综合得分**：按分类展示各模型综合得分
2. **各维度得分**：各模型在每个维度的得分
3. **良好率**：各维度达到阈值的样本占比
4. **改进建议**：从评测报告中提取的改进建议
5. **在线报告**：完整报告的网页链接

**注意事项**：
- 使用 `summary` 子命令可避免读取大文件，节省 Token
- **必须传入 `--platform_url` 参数**，确保在线报告链接被展示
- 若 `{platform_url}` 为空，需检查任务2的输出是否正确

---

## Red Flags

| 违规行为 | 正确做法 |
|----------|----------|
| 跳过前置验证 | 任务提交前必须检查eval-dimension.json、evalset-meta.json、eval-judge.json是否存在 |
| 未等待任务完成就展示结果 | 必须等待任务状态变为Succeeded或Failed后才能展示结果 |
| 未展示在线报告链接 | 任务成功后**必须**展示在线报告链接，便于用户查看完整报告 |

**常见借口与纠正**：

| 借口 | 现实 |
|------|------|
| "summary 命令会自动输出链接" | `--platform_url` 参数是必需的，不传入则不会输出 |
| "链接在结果文件中" | `platform_url` 只存在于轮询输出中，不在结果文件中 |
| "用户可以自己去平台查看" | 必须提供直接链接，提升用户体验 |

> 通用违规行为见 [SKILL.md Red Flags](./SKILL.md#red-flags---停止并检查)

---

## 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 任务提交失败 | 配置不完整或网络问题 | 检查配置文件完整性，确认网络连接 |
| 任务状态查询超时 | 网络不稳定或服务繁忙 | 增加超时时间或重试 |
| 结果展示失败 | 结果文件损坏或格式错误 | 检查结果文件完整性 |

> API 错误码见 [评测服务接口说明.md](./references/评测服务接口说明.md#错误码)

---

## 变量速查

变量定义见 [SKILL.md 变量速查](./SKILL.md#变量速查)