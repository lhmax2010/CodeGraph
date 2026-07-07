# Stage 06 - E2E Search/Definition / Result

## 最终状态
待真机验收 / 待 Merge。

P6 `search_symbol` + `get_definition` 端到端集成已实现，并按 design v1.4.5 / change_5 对齐：
MVP `background-index` 下 `search_symbol` 与 `get_definition` 均不产 `not_found`，空结果一律
`UNRESOLVED`。change_5 代码对齐已过用户异构 review；真机查询级验收数据已记录，待用户最终核对后
merge。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.99s`。
- 最新 UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 1.98s`。
- 覆盖率：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `142 passed`，total `93%`，`codegraph/api.py` `93%`，`codegraph/credibility.py` `96%`，`codegraph/engines/clangd_adapter.py` `100%`。
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
- 显式预热：`CodeGraph.prewarm()`、`prewarm_build_config()`、`register_build_config(..., prewarm=True)`。
- 预热语义：预热只焐热 cache，不授予后续查询跳过 `_warm_background_index` 的特权；后续查询仍每次证明本次 clangd ready。
- 预热 timeout：`BuildConfig.prewarm_index_ready_timeout=None` 时采用 `max(index_ready_timeout, 30.0)`；只影响预热，用户查询仍使用 `index_ready_timeout`。
- timeout 语义：sentinel `workspace/symbol` 使用剩余 wall-clock timeout，避免单次慢 LSP 请求无限顶穿等待窗口；`TimeoutError` 只表示 not-ready，查询继续安全降级。
- ready 语义硬化：`index_ready_probe_symbol` 必须与 `index_ready_probe_path_suffix` 配套；缺 suffix 直接 not-ready，不允许单 TU/header 命中把 `complete` health 带进 P2。
- `search_symbol` 分页硬化：exact 总命中数与当前页分开计算，`total_hits>0` 的空页不得落入项目级 `not_found`。
- `search_symbol` 截断窗口硬化：engine 返回数达到 `engine_limit` 且窗口内 exact 为 0 时，认为 fuzzy 窗口可能截断并保守降 `unknown/current_tu`，防 exact 排在窗口外时虚假 `not_found`。
- change_5 对齐：MVP `background-index` 下 `search_symbol` / `get_definition` 空结果一律 `UNRESOLVED`，不产 `not_found`。
- kind 元数据诚实性：`search_symbol(kind_filter=None)` 表示不过滤、任意符号，传 `SymbolKind.UNKNOWN`；显式 `function/variable/type` filter 保留真实 symbol_kind（如 function -> `ORDINARY_FUNCTION`），但空结果仍通过 health/scope guard 返回 `UNRESOLVED`，不失真元数据也不产 not_found。`get_definition` 无 kind filter，空结果用 `UNKNOWN`。
- P1 物理兜底：新增 INV14d，`index_backend=background-index ∧ resolved=not_found` 直接抛 `InvariantError("INV14D")`；`clangd-indexer + not_found` 放行，保留二期恢复条件。
- 工厂对齐：`clangd_not_found` 默认改为 `IndexBackend.CLANGD_INDEXER`，作为二期 not_found 工厂；MVP background-index 不再默认造非法 not_found。
- P3 兼容性硬化：`ClangdAdapterConfig` 恢复旧位置参数顺序，并运行时拒绝把 `background_index` 误传到第三个位置参数。

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
- 预热后首查复现：`CodeGraph(config).prewarm()` 后立即执行第一条用户查询 `get_definition(gst_buffer_ref @ gstbufferlist.c:91)`；最终默认 prewarm timeout 为 `30.0s`，本次 prewarm 1.408s 且 ready=True，紧接着第一条用户查询 1.581s -> `OK/complete`，语义结果 `gstbuffer.c:3014`；分片前后均为 `(3593, 39911040, 1781072784911021003)`，未重建。
- change_5 最终真机验收（2026-07-07，复用现有 3593 分片，不重建）：
  - 环境：真实 CDB `/home/linhao/Toolchain/codes/rw_arm`；query file 为 CDB 中的 `gstbufferlist.c`；`gst_buffer_ref` 调用点 zero-based `[90, 23]`；空 definition 验证用注释位置 `[88, 5]`；prewarm timeout 生效值 `30.0s`。
  - 索引快照：验收前 `(3593, 39911040, 1781072784911021003)`，验收后相同，确认复用分片、未触发重建。
  - Prewarm：`CodeGraph.prewarm()` -> `ready=True`，`1.331s`。
  - change_5 核心，真实不存在符号 `__codegraph_missing_symbol_20260707_change5__`：
    - `search_symbol(kind_filter=None)` -> `UNRESOLVED`，health=`unknown`，symbol_kind=`unknown`，`total_hits=0`。
    - `search_symbol(kind_filter=function)` -> `UNRESOLVED`，health=`unknown`，symbol_kind=`ordinary_function`，`total_hits=0`。
    - `search_symbol(kind_filter=variable)` -> `UNRESOLVED`，health=`unknown`，symbol_kind=`ordinary_variable`，`total_hits=0`。
    - `search_symbol(kind_filter=type)` -> `UNRESOLVED`，health=`unknown`，symbol_kind=`type`，`total_hits=0`。
    - `search_symbol(kind_filter=macro)` -> `UNRESOLVED`，health=`unknown`，symbol_kind=`macro`，`total_hits=0`。
    - `get_definition` 在注释位置空结果 -> `UNRESOLVED`，health=`unknown`，symbol_kind=`unknown`，`total_hits=0`。
  - 降 health/scope 不降 kind 真机确认：`kind_filter=function` 的空 search 保留 `symbol_kind=ordinary_function`，同时通过 health=`unknown` 阻断 not_found。
  - P6 端到端价值仍在：`search_symbol(gst_buffer_ref)` -> `OK/complete`，`1.429s`，语义结果 `gstbuffer.c:3014`；`get_definition(gst_buffer_ref)` 连续 3 次 -> `OK/complete`，约 `1.429-1.431s`，均命中 `gstbuffer.c:3014`，h→c 稳定不 miss。
  - bg=False 安全底线：`search_symbol(gst_buffer_ref)` -> `UNRESOLVED/unknown`，非 not_found；`get_definition(gst_buffer_ref)` -> `UNRESOLVED/unknown`，非 not_found。

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
  - 本次提交：`[Phase 6] fix: prewarm background index and bound sentinel wait`
  - 本次 follow-up：`[Phase 6] fix: require ready probe suffix and preserve search totals`
  - `d859849 [Phase 6] fix: prevent not_found from truncated symbol windows`
  - `eb6e865 [Phase 6] fix: prevent unfiltered symbol searches from asserting not_found`
  - `284dfd9 [Phase 6] align: change_5 no not_found under background-index`
  - 本轮 HEAD：`[Phase 6] chore: record change_5 true-machine acceptance`
- Review artifact：`docs/review/phase_6_review_result.md`。

## P6 前的账验证情况
- P5 全局索引消费：已验证。P6 需要显式 `background_index=True`，并通过 warm TU + sentinel 等待全局索引 ready。
- `diagnostics_wait=0.5s` 大型 Tizen TU 风险：P6 的 `search_symbol/get_definition` 真实查询未暴露 missing-include 漏诊断；该项仍需要后续用真实 missing-include 大 TU 做针对性回归。
- P4 候选符号过度采集：P6 真实查询中 fallback candidates 只作为 `not_evidence` 候选，不会支撑 OK/not_found；候选质量收紧仍留到后续真实代码阶段。
- 宏体保守近似 / clangd 宏相关真实位置：本阶段 `gst_buffer_ref` 等查询未覆盖宏位置粒度；仍需 P7/P8 或专门宏真机用例验证。
- `change_4` tree-sitter 要素2集成：P6 已经通过 P4 provider 参与 fallback 和降级路径；宏定义/宏展开的真实 clangd 位置仍按上一条保留。

## 遗留问题 / 风险
- [P7 前·调用说明] sentinel 必须配置：`background_index=True` 但未配置 `index_ready_probe_symbol` 或未配置 `index_ready_probe_path_suffix` 时会恒 `unknown`，拿不到项目级 not_found/complete 语义结论。这是 secure-by-default；调用方应配置稳定的 `index_ready_probe_symbol` + `index_ready_probe_path_suffix` + `warmup_file`。
- [P7 前] sentinel 配错会静默降级：错 symbol 或错 suffix 会导致每次查询轮询到 `index_ready_timeout` 后降为 `unknown`。本轮不顺手加 `log.warning`，避免四路 review 后再引入未经复核的新代码路径；建议 P7 前补 warning 或调用侧可观测信号。
- [P7 前] sentinel probe 当前 `limit=20` 硬编码；极端 common symbol 前 20 条可能不含期望 suffix。后续可配置化或分页探测。
- [核对前] P6 真机查询级验收已完成并记录，待用户最终核对后 merge。
- [P7 前·harden] 截断判据目前比较 P6 `engine_limit` 与 adapter 返回数，依赖 `engine_limit=100` 与 clangd `workspace/symbol` 实际返回 cap 对齐；offset>0、kind_filter 本地缩小计数、换引擎/换 clangd 行为时可能漏检 clangd 层截断。P7 前应让截断判据对齐真实 engine cap/原始返回规模，不依赖 100==100 的巧合。
- [后续架构优化] 当前 `CodeGraph` 每次查询新起 clangd；显式预热只能焐热 OS page cache / `.idx` 读取路径，不能让后续查询跳过 ready 证明。clangd 常驻/进程池可作为独立后续优化，不纳入 P6。
- [NIT] ready 后 `_health_after_warm()` 会重新读取 index health，存在轻微重复 IO，不影响正确性。
- [NIT] `search_symbol` 已修复“先分页再 exact”的主要问题；若极端场景中 fuzzy 结果超过过量窗口，仍可能漏掉更靠后的 exact，后续可观察。

## 下一阶段计划
- 约 P6 真机验收，确认最终 DoD 后 merge `phase/6-e2e-search-def` 到 `main`。
