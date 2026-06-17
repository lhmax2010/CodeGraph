# Stage 04 - Treesitter / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 4 开 stage baseline 取 `main@46ed936`，从该提交新建 `phase/4-treesitter`。
  - 原因：stage03_clangd_adapter 已 Merge，change_4 v1.4.4 已落库并作为 P4 基线。
  - 排除的方案：从 `checkpoint/phase_3_clangd_adapter` 开发。该方案会漏掉 v1.4.4 设计基线提交。
- 决策：Phase 4 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P4 引入真实 tree-sitter、实现 P6 前置 syntax helper，并需外科式修改已 Merge 的 P2 宏短路。
  - 排除的方案：按普通风险推进。该方案低估了 P2 回改和要素2误判的影响。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage04_treesitter` 为当前活跃 stage，更新设计基线到 v1.4.4。
- 文件/模块：`.dev_memory/stage04_treesitter/plan.md`
  - 改动内容：记录 Phase 4 目标、范围边界、计划步骤、baseline、tree-sitter 环境与风险档候选。
- 文件/模块：`.dev_memory/stage04_treesitter/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage04_treesitter/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 4 收尾时填写。

## 进度日志
- [2026-06-17] 读取 `docs/design.md` v1.4.4、`docs/design_changes/change_4.md`、`.dev_memory/INDEX.md`、stage01/stage02/stage03 result、P4/P6 设计章节、P1/P2 接缝代码；确认 P4 要实现 tree-sitter provider + syntax helper，并只精确移除 P2 的 `symbol_kind==MACRO` 短路。
- [2026-06-17] 当前 `main` 位于 `46ed936 [design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`，工作树干净。
- [2026-06-17] 在 `main@46ed936` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.21s`。
- [2026-06-17] tree-sitter 环境预检：裸 `python3` 不能 import `tree_sitter`；`uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4` 可 import；微型 C parse 能识别 `preproc_def` / `preproc_arg`。
- [2026-06-17] 从 `main@46ed936` 新建分支 `phase/4-treesitter`。
- [2026-06-17] 创建 `.dev_memory/stage04_treesitter/` 计划与进度骨架；等待风险档与 restate gate 确认后再实现。
- [2026-06-17] 环境确认：系统 `/usr/bin/python3` 受 PEP 668 管理，`python3 -m pip install --dry-run tree-sitter...` 被拒；`python3 -m venv .venv` 因缺 `ensurepip` 失败；改用 `uv venv --allow-existing --seed .venv` 建立项目本地 venv 并安装 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4`、`pytest`、`pytest-cov`。
- [2026-06-17] `.venv/bin/python` 直接 import tree-sitter 成功，微型 C parse 识别 `preproc_def` / `preproc_arg`；`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `90 passed in 0.24s`。
