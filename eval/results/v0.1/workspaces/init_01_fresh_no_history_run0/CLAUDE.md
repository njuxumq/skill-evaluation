# 脚本路径覆盖（强制）

本工作区使用独立的 eval_skill.py 脚本。执行任何 eval_skill.py 命令时，必须使用以下绝对路径，禁止使用 Skill 文档中的 `{skill-dir}` 变量：

```
/home/mqxu11/projects/claude/skill-evaluation/eval/results/v0.1/workspaces/init_01_fresh_no_history_run0/.claude/skills/skill-evaluation/eval_skill.py
```

示例：`python3 "/home/mqxu11/projects/claude/skill-evaluation/eval/results/v0.1/workspaces/init_01_fresh_no_history_run0/.claude/skills/skill-evaluation/eval_skill.py" check-token --auth-file ...`
