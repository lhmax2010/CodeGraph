# Stage 05 - Index Build / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 5 开 stage baseline 取 `main@d2c381b`，从该提交新建 `phase/5-index-build`。
  - 原因：stage04_treesitter 已 Merge，P5 应基于 P4 收口点继续。
  - 排除的方案：从旧 P4 分支或 checkpoint 之前提交开发。该方案会漏掉 P4 收尾记录与 checkpoint。
- 决策：Phase 5 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P5 首次接真实 GBS/ARM、background-index 分片和索引健康判定；误报 complete 会影响后续 not_found 输入。
  - 排除的方案：按普通风险推进。该方案低估了环境依赖和 index_health 对虚假否定护栏的影响。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage05_index_build` 为当前活跃 stage。
- 文件/模块：`.dev_memory/stage05_index_build/plan.md`
  - 改动内容：记录 Phase 5 目标、范围边界、环境探测、baseline 与风险档候选。
- 文件/模块：`.dev_memory/stage05_index_build/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage05_index_build/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 5 收尾时填写。

## 进度日志
- [2026-06-18] 读取 `docs/design.md` v1.4.4、`docs/design_changes/change_1/2/3/4.md`、`.dev_memory/INDEX.md`、stage01-stage04 result、P5 设计章节；确认 P5 只产出 `index_health`，不做 not_found 判定。
- [2026-06-18] 当前 `main` 位于 `d2c381b [Phase 4] docs: close treesitter stage before merge`，工作树干净。
- [2026-06-18] 环境探测：`tools/cdb_rewriter.py` 存在、可 import、CLI 可运行；`gbs 2.0.6` 可用；`clangd 18.1.3` 可用；`clang` 命令不存在但 P5 使用 clangd。
- [2026-06-18] 探测到真实 CDB：`rw_x86/compile_commands.json` 207 entries / 157 unique TU；`rw_arm/compile_commands.json` 1304 entries / 1303 unique TU；两者 entry 文件均存在，且包含已改写的 `--sysroot` / `--target`。
- [2026-06-18] 探测到真实 background-index 分片：`rw_x86/.cache/clangd/index` 1178 `.idx` / 9.5M；`rw_arm/.cache/clangd/index` 3593 `.idx` / 47M；按 shards≥TU 下界均为 complete。
- [2026-06-18] 小型临时工程实跑 `clangd --background-index=true` 成功产出 `.cache/clangd/index/main.c....idx`，确认当前环境可新建 background-index。
- [2026-06-18] 读取既有 `/home/linhao/Toolchain/codes/global-index-feasibility-report.md` 与日志，确认 ARM 1303 TU 首建约 50s、运行时加载 ≤10s 的历史真机数据存在；本次准备阶段未重跑完整 50s 建库。
- [2026-06-18] 在 `main@d2c381b` 跑 baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.21s`。
- [2026-06-18] 从 `main@d2c381b` 新建分支 `phase/5-index-build`。
- [2026-06-18] 创建 `.dev_memory/stage05_index_build/` 计划与进度骨架；等待风险档与 restate gate 确认后再实现。
