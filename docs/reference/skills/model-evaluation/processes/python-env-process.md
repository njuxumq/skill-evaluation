# Python 环境检测流程

## 适用场景

- 初始化阶段检测 Python 环境
- 环境缓存失效时重新检测

## 输出

| 变量 | 说明 |
|------|------|
| `{python-cmd}` | Python 命令（`python3` 或 `python`） |
| `{python-env}` | 环境变量前缀（Windows GBK 为 `PYTHONUTF8=1 `，其他为空） |

---

## 流程步骤

### 步骤1：检测 Python 命令

依次尝试 `python3` 和 `python` 命令：

```bash
python3 --version
```

- **返回版本信息** → 设置 `{python-cmd}` 为 `python3` → 进入步骤2
- **命令不存在** → 尝试备用命令：

```bash
python --version
```

- **返回 Python 3.x** → 设置 `{python-cmd}` 为 `python`（注意，不是 `python3`） → 进入步骤2
- **返回 Python 2.x** → 查找 Python 3 路径或提示用户安装
- **命令不存在** → 提示用户安装 Python 3

---

### 步骤2：检测依赖

执行一次命令检测所有依赖：

```bash
{python-cmd} -c "
deps = [
    ('requests', '必需'),
    ('pandas', '可选'),
    ('openpyxl', '可选')
]
installed = []
missing = []
for name, category in deps:
    try:
        __import__(name)
        installed.append(name)
    except ImportError:
        missing.append(f'{name}({category})')
print('OK' if not missing else 'MISSING')
print('已安装:', ', '.join(installed))
print('缺失:', ', '.join(missing) if missing else '无')
"
```

**输出示例**：

| 情况 | 输出 |
|------|------|
| 全部已安装 | `OK`<br>`已安装: requests, pandas, openpyxl`<br>`缺失: 无` |
| 部分缺失 | `MISSING`<br>`已安装: requests`<br>`缺失: pandas(可选), openpyxl(可选)` |

**后续动作**：

- **输出 OK**（无缺失） → 进入步骤3
- **输出 MISSING**（有缺失） → 根据缺失项提示安装：
  - 缺失 `requests`：`pip install requests`
  - 缺失 `pandas` 或 `openpyxl`：`pip install pandas openpyxl`

> **说明**：`requests` 用于 HTTP 请求，是必需依赖；`pandas` 用于数据处理，`openpyxl` 是 pandas 读取 Excel 的引擎，两者为可选依赖

---

### 步骤3：检测编码环境

```bash
{python-cmd} -c "import sys; print(sys.platform)"
```

根据检测结果设置 `{python-env}` 变量：

| sys.platform | 终端编码页 | `{python-env}` 值 |
|--------------|-----------|------------------|
| `win32` | 非65001 | `PYTHONUTF8=1 ` |
| `win32` | 65001 | 空 |
| 其他 | - | 空 |

检测终端编码页（仅 Windows）：`chcp`，输出包含 `65001` 则为 UTF-8 模式。

---

## 使用示例

在调用脚本时使用 `{python-env}` 前缀：

```bash
{python-env}{python-cmd} scripts/eval_auth.py check --output {work-dir}/.eval/auth.json
```

Windows GBK 终端下，`{python-env}` 为 `PYTHONUTF8=1 `，实际执行：

```bash
PYTHONUTF8=1 python scripts/eval_auth.py check --output {work-dir}/.eval/auth.json
```