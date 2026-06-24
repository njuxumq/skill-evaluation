---
name: eval-init
description: Use when starting a new evaluation task or resuming an existing one, before any build or execute operations
---

# 初始化阶段

## 目标

完成Python环境检测、鉴权验证、会话目录确认后，进入构建阶段。

核心原则：**缓存优先，按序执行，失败即止**。

## 何时使用

- 开始新的评测任务时
- 继续历史评测任务时
- 环境或鉴权状态不明时

---

## 阶段完成标志

**验证顺序**（按序执行，任一失败则执行对应任务）：

1. 检查 `{work-dir}/.eval/env.cfg` 存在且字段完整 → 否则执行任务1
2. 检查 `{work-dir}/.eval/auth.json` 存在且Token有效 → 否则执行任务2
3. 检查 `{work-dir}/.eval/{session-id}/` 目录存在 → 否则执行任务3

全部通过后，进入构建阶段（加载 `eval-build.md`）。

---

## 任务列表

### 任务1：环境及依赖检测

#### 步骤1：检查环境缓存文件

检查 `{work-dir}/.eval/env.cfg` 是否存在。

- **文件存在** → 进入步骤2（验证缓存有效性）
- **文件不存在** → 进入步骤3（执行环境检测）

---

#### 步骤2：验证缓存有效性

读取 `{work-dir}/.eval/env.cfg` 文件，检查以下字段：

| 字段 | 要求 |
|------|------|
| `python_cmd` | 非空 |
| `python_env` | 非空 |
| `deps_required` | 非空 |

- **字段完整** → 设置 `{python-cmd}` 为 `python_cmd` 值，设置 `{python-env}` 为 `python_env` 值，完成本任务
- **字段缺失** → 缓存无效 → 步骤3

---

#### 步骤3：执行环境检测

调用 [Python 环境检测流程](processes/python-env-process.md)，依次执行：

1. 检测 Python 命令 → 确定 `{python-cmd}`
2. 检测依赖 → 确保必需依赖已安装
3. 检测编码环境 → 确定 `{python-env}`

**输出变量**：

| 变量 | 说明 |
|------|------|
| `{python-cmd}` | Python 命令（`python3` 或 `python`） |
| `{python-env}` | 环境变量前缀（Windows GBK 为 `PYTHONUTF8=1 `，其他为空） |

- **检测成功** → 进入步骤4
- **检测失败** → 根据错误提示用户安装或配置

---

#### 步骤4：生成环境缓存文件

创建 `{work-dir}/.eval/env.cfg`：

```ini
python_cmd={python-cmd}
python_env={python-env}
deps_required=requests
deps_optional={可选依赖，已安装为pandas,openpyxl，未安装为空}
# 说明：pandas 用于数据处理，openpyxl 是 pandas 读取 Excel 的引擎
created_at={当前时间戳}
```

完成本任务。

---

> **重要提示**：执行脚本时使用 `{python-env}` 前缀
>
> 在后续所有脚本调用中，必须使用 `{python-env}{python-cmd}` 格式执行命令：
>
> ```bash
> {python-env}{python-cmd} {skill-dir}/scripts/eval_auth.py check --output {work-dir}/.eval/auth.json
> ```
>
> Windows GBK终端下，`{python-env}` 为 `PYTHONUTF8=1 `，实际执行：`PYTHONUTF8=1 python scripts/eval_auth.py check --output {work-dir}/.eval/auth.json`

---

### 任务2：确保鉴权Token有效

#### 步骤1：检查鉴权文件

检查 `{work-dir}/.eval/auth.json` 是否存在。

- **文件不存在** → 进入步骤2
- **文件存在** → 进入步骤3

---

#### 步骤2：智能登录授权

**⚠️ 不可跳过**：用户必须在浏览器完成授权后输入授权码，此流程无法绕过。

执行智能登录命令：
```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_auth.py login --config {skill-dir}/scripts/cfg/eval-auth.cfg --output {work-dir}/.eval/auth.json
```

脚本自动检测运行环境并选择登录模式。

**输出处理**：

| status | 说明 | 后续动作 |
|--------|------|----------|
| `success` | 自动完成，Token已获取 | 完成本任务 |
| `manual_url` | 需手动授权 | 执行下方手动授权流程 |

**手动授权流程**（status=`manual_url`时执行）：

1. 展示输出中的 `login_url`，提示用户访问并完成授权
2. 等待用户返回授权码（用户主动输入，不使用 AskUserQuestion）
3. 获取授权码后执行token命令：
```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_auth.py token --code {授权码} --state_token {输出中的state_token} --config {skill-dir}/scripts/cfg/eval-auth.cfg --output {work-dir}/.eval/auth.json
```

**可选参数**：`--mode auto|manual`（强制指定模式）。

---

#### 步骤3：验证Token有效性

```bash
{python-env}{python-cmd} {skill-dir}/scripts/eval_auth.py check --output {work-dir}/.eval/auth.json
```

| status | 说明 | 后续动作 |
|--------|------|----------|
| `valid` | Token有效 | 完成本任务 |
| `invalid` | Token已失效 | 进入步骤2 |
| `not_found` | 文件不存在 | 进入步骤2 |

---

### 任务3：确认会话目录

#### 步骤1：分析用户意图

结合分析历史对话，分析用户意图。判断如下：

| 用户意图 | 判断依据 | 后续动作 |
|----------|----------|----------|
| 新建评测任务 | 对话中提及"新建"、"创建"、"开始新的" | → 步骤3 |
| 继续旧任务 | 对话中提及会话ID或"继续"某任务 | → 步骤2 |
| 无法判断 | 无历史对话或意图不明确 | → 步骤2 |

---

#### 步骤2：选择历史会话

扫描并展示历史会话列表，格式：`| 会话ID | 评测场景 | 状态 |`。

- **选择历史任务** → 使用对应的 `{session-id}`，完成本任务
- **输入 'new'** → 进入步骤3

---

#### 步骤3：创建新会话目录

命名规则：`session-{8位字母数字}`，示例：`session-a3c8f4ci`
```bash
session_id="session-$(tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 8)"
```

```bash
mkdir -p {work-dir}/.eval/{session-id}
```

---

## Red Flags

| 违规行为 | 简洁理由 |
|----------|----------|
| 跳过缓存检测 | 缓存优先原则 |
| 跳过重新授权 | Token失效必须重新授权 |
| 未验证环境继续执行 | 环境验证是前置条件 |

> 通用违规行为见 [SKILL.md Red Flags](./SKILL.md#red-flags---停止并检查)

**常见借口**：

| 借口 | 现实 |
|------|------|
| "评测集可以先问用户" | 评测集属于构建阶段，不可提前询问 |
| "场景可以提前确认" | 场景属于构建阶段，不可提前询问 |

> 用户明确指明跳转时，可直接进入对应阶段。

## 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| Python命令不可用 | 未安装Python 3.x | 提示安装Python 3.x |
| Python版本不兼容 | 系统默认Python 2.x | 创建别名或使用正确命令 |
| Token已失效 | Token过期或被撤销 | 引导用户重新授权 |
| 浏览器打开失败 | 服务器终端无图形界面 | 用户手动访问登录链接 |
| 非交互式终端 | 在管道或脚本中运行 | 使用 `login` 和 `token` 子命令分步执行 |
| 跳过缓存直接检测 | 忽略步骤顺序 | 严格按步骤1→8顺序执行 |

---

## 变量速查

变量定义见 [SKILL.md 变量速查](./SKILL.md#变量速查)