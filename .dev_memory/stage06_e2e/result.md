# Stage 06 - E2E Search/Definition / Result

## 最终状态
待真机验收 / 待 Merge。

P6 `search_symbol` + `get_definition` 端到端集成已实现并修复两处 review BLOCKER。四路异构 review
与真机复现确认两个虚假否定问题已堵住；merge 前剩余事项是 P6 真机验收收口。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.99s`。
- 最新 UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `124 passed in 1.94s`。
- 覆盖率：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `124 passed`，total `91%`，`codegraph/api.py` `82%`，`codegraph/engines/clangd_adapter.py` `100%`。
- 静态 gate：
  - `.venv/bin/ruff check .` -> All checks passed。
  - `.venv/bin/black --check .` -> 22 files unchanged。
  - `.venv/bin/mypy codegraph` -> Success: no issues found。
  - `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。

## 补测内容
- P6 API 小 CDB 端到端：`search_symbol` 与 `get_definition` 接 P3/P4/P5/P2 全链路。
- P3 兼容性：`ClangdAdapterConfig.background_index` 默认仍为 `False`，P3 单 TU 测试保持可预测。
- 防虚假否定：
  - `background_index=False` 时空结果不得借 P5 `complete` 进入 `not_found`。
  - background-index 未 ready 时 `index_health` 降为 `unknown`、scope 降为 `current_tu`。
  - ready 使用 query-independent sentinel，不被用户查询 symbol 的 header/单 TU 命中误触发。
  - sentinel path suffix 不匹配时不标 ready。
- `search_symbol` 精确过滤：先过量拉取再 exact filter + 用户侧 `limit/offset`，避免 fuzzy 命中挤掉 exact。
- 非法输入、engine failure、module-level registry 分支补测。

## 真机 ARM / P5 全局索引复现
- 环境：`clangd 18.1.3`；真实 ARM CDB `/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`；P5 索引目录含 `3593` 个 `.idx` 分片。
- 索引复用：`clangd --background-index=true` + cwd/compile dir 指向 `rw_arm` 后复用现有 P5 分片，未触发 31s 重建。
- 索引 ready：只 initialize 不 open TU 时 `workspace/symbol(gst_element_set_state)` 轮询 12s 仍为 0；open/warm 一个真实 TU 后，约 `1.213s` 返回 `.c` 命中，`find_references` 约 `5.266s` 复现 `389 refs`。
- `get_definition` 全局索引能力：扫描 180 个真实 CDB 源文件/1702 个调用探针，确认存在单 TU 到 header、全局索引到 `.c` 实现的差异。例如：
  - `gstbufferlist.c:91 gst_buffer_ref`：单 TU -> `gstbuffer.h:463`；全局 -> `gstbuffer.c:3014`。
  - `gstbufferlist.c:35 gst_pad_push_list`：单 TU -> `gstpad.h:1515`；全局 -> `gstpad.c:4920`。
  - `gstcontext.c:35 gst_element_set_context`：单 TU -> `gstelement.h:1016`；全局 -> `gstelement.c:3604`。
- BLOCKER 修复后复现：
  - `background_index=False search_symbol(gst_buffer_ref)` -> `UNRESOLVED/index_unknown`，非 `not_found`。
  - `background_index=False get_definition(gst_buffer_ref)` -> `UNRESOLVED/index_unknown`，非 `not_found`。
  - `background_index=True` 且 sentinel=`gst_buffer_ref`、suffix=`gstbuffer.c`：
    - `search_symbol(gst_buffer_ref)` -> `OK/complete`，语义结果 `gstbuffer.c:3014`。
    - `get_definition(gst_buffer_ref)` -> `OK/complete`，语义结果 `gstbuffer.c:3014`。
  - `get_definition(gst_buffer_ref)` 连续 3 次均稳定命中 `gstbuffer.c:3014`，每次约 `1.57-1.59s`。
- 无 sentinel 复现：`background_index=True` 但未配置 `index_ready_probe_symbol` 时，`search_symbol`/`get_definition` 均保守为 `UNRESOLVED/index_unknown`，只给 syntactic candidates，不给语义 OK 或 not_found。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`7717257 [Phase 5] docs: record index build checkpoint`。
- 当前分支：`phase/6-e2e-search-def`。
- 对应 Git Commit：
  - `d900b82 [Phase 6] chore: open e2e search/definition stage`
  - `dfe22fc [Phase 6] feat: wire search and definition e2e`
  - `9eafba4 [Phase 6] docs: record get_definition background-index proof`
  - `2e1a9d1 [Phase 6] fix: prevent false negatives before global index ready`
  - `9774bdc [Phase 6] docs: record blocker review follow-up`
- Review artifact：`docs/review/phase_6_review_result.md`。

## P6 前的账验证情况
- P5 全局索引消费：已验证。P6 需要显式 `background_index=True`，并通过 warm TU + sentinel 等待全局索引 ready。
- `diagnostics_wait=0.5s` 大型 Tizen TU 风险：P6 的 `search_symbol/get_definition` 真实查询未暴露 missing-include 漏诊断；该项仍需要后续用真实 missing-include 大 TU 做针对性回归。
- P4 候选符号过度采集：P6 真实查询中 fallback candidates 只作为 `not_evidence` 候选，不会支撑 OK/not_found；候选质量收紧仍留到后续真实代码阶段。
- 宏体保守近似 / clangd 宏相关真实位置：本阶段 `gst_buffer_ref` 等查询未覆盖宏位置粒度；仍需 P7/P8 或专门宏真机用例验证。
- `change_4` tree-sitter 要素2集成：P6 已经通过 P4 provider 参与 fallback 和降级路径；宏定义/宏展开的真实 clangd 位置仍按上一条保留。

## 遗留问题 / 风险
- [P7 前·调用说明] sentinel 必须配置：`background_index=True` 但未配置 `index_ready_probe_symbol` 时会恒 `unknown`，拿不到项目级 not_found/complete 语义结论。这是 secure-by-default；调用方应配置稳定的 `index_ready_probe_symbol` + `index_ready_probe_path_suffix` + `warmup_file`。
- [P7 前] sentinel 配错会静默降级：错 symbol 或错 suffix 会导致每次查询轮询到 `index_ready_timeout` 后降为 `unknown`。本轮不顺手加 `log.warning`，避免四路 review 后再引入未经复核的新代码路径；建议 P7 前补 warning 或调用侧可观测信号。
- [P7 前] sentinel probe 当前 `limit=20` 硬编码；极端 common symbol 前 20 条可能不含期望 suffix。后续可配置化或分页探测。
- [P7 前] `codegraph/api.py` 覆盖率为 `82%`，低于核心 90% 目标；BLOCKER 路径已覆盖，剩余主要是异常/边界分支。真机验收后补异常分支测试。
- [NIT] ready 后 `_health_after_warm()` 会重新读取 index health，存在轻微重复 IO，不影响正确性。
- [NIT] `search_symbol` 已修复“先分页再 exact”的主要问题；若极端场景中 fuzzy 结果超过过量窗口，仍可能漏掉更靠后的 exact，后续可观察。

## 下一阶段计划
- 约 P6 真机验收，确认最终 DoD 后 merge `phase/6-e2e-search-def` 到 `main`。
