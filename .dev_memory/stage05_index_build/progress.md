# Stage 05 - Index Build / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 5 开 stage baseline 取 `main@d2c381b`，从该提交新建 `phase/5-index-build`。
  - 原因：stage04_treesitter 已 Merge，P5 应基于 P4 收口点继续。
  - 排除的方案：从旧 P4 分支或 checkpoint 之前提交开发。该方案会漏掉 P4 收尾记录与 checkpoint。
- 决策：Phase 5 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P5 首次接真实 GBS/ARM、background-index 分片和索引健康判定；误报 complete 会影响后续 not_found 输入。
  - 排除的方案：按普通风险推进。该方案低估了环境依赖和 index_health 对虚假否定护栏的影响。
- 决策：开发期先用现有 `rw_arm` / `rw_x86` 分片验证 P5 逻辑，完整 ARM 重建留到 P5 收口验收前单独确认窗口。
  - 原因：现有真实分片足够覆盖 CDB/TU 统计、shards≥TU 下界和三态 health；完整 ARM 建库约 50s 且写盘，按用户要求不在开发循环里反复触发。
  - 排除的方案：每次实现/测试都重跑 ARM 全量建库。该方案耗时且增加磁盘 churn，不提升单元逻辑验证价值。
- 决策：P5 模块只产出 `index_health` 事实与索引构建元数据，不做任何 not_found/负证明判定。
  - 原因：设计明确 not_found 级别由 P2 根据 `index_health` 决定；P5 误塞判定会破坏职责边界。
  - 排除的方案：在 P5 根据 complete 直接给出项目级可负证明结论。该方案越界且会削弱 INV14/P2 钳制。
- 决策：P5 的所有 gate 继续使用 `.venv/bin/python` 及 `.venv` 内工具。
  - 原因：P4 起 tree-sitter 安装在项目 `.venv`，P5 回归必须在同一运行环境里复现，避免系统 Python 因缺可选 binding 得到假失败。
  - 排除的方案：混用系统 `python3` 跑测试。该方案与 P4/P5 的实际本地服务运行模型不一致。
- 决策：`index_health` 覆盖率粗判严格使用 `idx_shards >= unique_TU_count` 下界。
  - 原因：design §7 Phase 5 要求这是保守下界，不用比例阈值；P5 只低估完整性，不乐观放大索引健康。
  - 排除的方案：使用 `idx_shards / TU >= 0.95` 之类比例。该方案会把真实缺分片误报为 complete。
- 决策：CLI 同时支持 `--inspect-only` 读取现有分片和 `--input-cdb` 从 GBS CDB 改写后驱动 clangd background-index。
  - 原因：开发期需要快速验证现有 ARM/x86 分片；P5 验收又必须证明从 CDB 到 `.idx` 的完整流程可跑。
  - 排除的方案：只实现读现成 `.idx`。该方案无法满足 Phase 5 DoD 的“可复现建库”要求。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage05_index_build` 为当前活跃 stage。
- 文件/模块：`.dev_memory/stage05_index_build/plan.md`
  - 改动内容：记录 Phase 5 目标、范围边界、环境探测、baseline 与风险档候选。
- 文件/模块：`.dev_memory/stage05_index_build/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage05_index_build/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 5 收尾时填写。
- 文件/模块：`codegraph/indexing.py`
  - 改动内容：新增 compile_commands 摘要、`.idx` 分片扫描、三态 `index_health` 评估、GBS CDB 改写封装、clangd background-index 驱动。
- 文件/模块：`tools/build_index.py`
  - 改动内容：新增 P5 CLI，支持 inspect-only、GBS CDB 改写、background-index 构建并输出结构化 JSON。
- 文件/模块：`tests/test_indexing.py`
  - 改动内容：覆盖 unique TU 去重、`command` 字符串解析、complete/incomplete/unknown 三态、复用 `cdb_rewriter`、小型真实 clangd 建库、真实 ARM/x86 现有分片、CLI inspect-only、CLI CDB→分片端到端。

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
- [2026-06-18] 用户确认高风险档与 P5 落地方式：开发期复用现有 ARM/x86 分片验证逻辑；P5 收口前再确认窗口并重跑一次 ARM 完整建库作为 DoD 验收。
- [2026-06-18] 实现 `codegraph.indexing`：只产出 `IndexHealthReport` 与索引构建事实，未加入任何 not_found/负证明判断。
- [2026-06-18] 实现 `tools/build_index.py`：`--compile-commands-dir --inspect-only` 用于现有分片验逻辑；`--input-cdb --output-dir --buildroot` 复用 `tools/cdb_rewriter.py` 后启动 clangd background-index。
- [2026-06-18] 定向测试：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_indexing.py -q` -> `8 passed in 1.18s`。
- [2026-06-18] 全量回归：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `105 passed in 1.37s`。
- [2026-06-18] 静态 gate：`.venv/bin/ruff check .` -> `All checks passed!`；`.venv/bin/black --check .` -> `20 files would be left unchanged`；`.venv/bin/mypy codegraph` -> `Success: no issues found in 10 source files`；`.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。
- [2026-06-18] 覆盖率：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `105 passed`，总覆盖率 92%，`codegraph/indexing.py` 90%。
- [2026-06-18] 真实现有分片 inspect-only：ARM `/home/linhao/Toolchain/codes/rw_arm` -> `complete shards_ge_unique_tu 3593 1303`；x86 `/home/linhao/Toolchain/codes/rw_x86` -> `complete shards_ge_unique_tu 1178 157`。
- [2026-06-18] 小型 CLI 端到端测试已覆盖 `input_cdb -> cdb_rewriter -> clangd background-index -> .idx -> complete`；完整 ARM 50s 重建尚未触发，按用户要求等 P5 收口验收前确认窗口。
