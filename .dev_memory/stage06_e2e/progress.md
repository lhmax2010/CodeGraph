# Stage 06 - E2E Search/Definition / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：P6 风险档定为高风险。
  - 原因：这是 P1-P5 首次真实集成，主要风险来自 clangd/P5 索引、P4 helper、P2 路由契约之间的接缝。
  - 排除的方案：不把 P6 当作单模块实现阶段处理。
- 决策：P6 先接链路跑真实查询，再针对性处理 P6 前遗留项。
  - 原因：P6 的核心价值是暴露集成问题；预防性返工 P3/P4 容易扩大范围并掩盖真实接缝。
  - 排除的方案：开工前逐个预防性修完 `diagnostics_wait`、候选过度采集、宏体近似。
- 决策：P6 必须显式处理 clangd background-index 模式。
  - 原因：当前 `ClangdAdapter` 复用的 `LSPClient` 默认带 `--background-index=false`，与 P5 result 里 2 refs vs 389 refs 的证据一致；真实跨文件查询需要消费 P5 全局索引。
  - 排除的方案：沿用单 TU 模式冒充端到端。
- 决策：P6 API 在 background-index readiness 未确认时，把本次查询的 `index_health` 降为 `unknown`。
  - 原因：clangd background-index 异步加载；若空结果发生在索引未 ready 阶段，继续传 P5 `complete` 会让 P2 可能走 not_found，形成虚假否定。
  - 排除的方案：只看 P5 分片健康就允许空结果进入 not_found 分支。
- 决策：background-index ready 必须由查询无关的 sentinel 证明，不能用用户查询 symbol 非空作为 ready 判据。
  - 原因：用户 symbol 可能在单 TU/include header 中立即可见，误触发 ready 后 `get_definition` 会不稳定地停在 `.h` 声明，未等到全局 `.c` 实现。
  - 排除的方案：继续用 `search_symbol(query_symbol)` 非空作为 ready；固定 sleep 后不验证全局索引。
- 决策：`background_index=False` 的 API 查询一律视为未消费全局索引，传给 P2 的 `index_health` 降为 `unknown`、`index_scope` 降为 `current_tu`。
  - 原因：bg=False 是 P3 单 TU 可预测模式，即使 P5 分片健康也不能据此做本次查询的项目级负证明。
  - 排除的方案：沿用 P5 `complete` health 让空结果进入 not_found。

## 改动摘要
- 文件/模块：
  - `.dev_memory/INDEX.md`：登记 stage06 进行中。
  - `.dev_memory/stage05_index_build/result.md`：校正 stage05 已 Merge 事实。
  - `.dev_memory/stage06_e2e/plan.md`：记录 P6 计划、边界、集成问题。
  - `tools/verify_clangd.py`：对复用资产做最小修改，为 `LSPClient` 增加 `background_index` 可选参数，默认仍为 `False`。
  - `codegraph/engines/clangd_adapter.py`：`ClangdAdapterConfig` 增加 `background_index` 开关，默认 `False`，并新增 `warm_file()` 供 P6 触发 clangd 加载 CDB/索引。
  - `codegraph/api.py`：新增 P6 库 API 薄层，组装 P3/P4/P5 后调用 P2 routing。
  - `tests/test_api.py`：新增 P6 API 端到端/防虚假 not_found/非法输入/engine failure/精确过滤测试。
  - `codegraph/api.py`：修复 review BLOCKER：bg=False 不再携带 P5 complete 做负证明；background-index ready 改为配置化 sentinel（symbol + path suffix）证明；`search_symbol` 改为先过量拉取再精确过滤/分页，避免 fuzzy 命中挤掉精确结果。
  - `tests/test_api.py`：补 blocker 回归：bg=False 空结果必须 UNRESOLVED/unknown；ready 不被 query symbol/header 命中误触发；suffix 不匹配不标 complete；engine failure/非法输入/module registry 分支。

## 进度日志
- 2026-07-01 从 `main` 开 `phase/6-e2e-search-def`，baseline `7717257 [Phase 5] docs: record index build checkpoint`。
- 2026-07-01 baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.99s`。
- 2026-07-01 探测：`/home/linhao/Toolchain/codes/rw_arm/.cache/clangd/index` 存在 3593 个 `.idx`；P5 验收临时 `/tmp/codegraph-p5-arm-index-20260624-154443` 已不可用，P6 可复用现有真实分片。
- 2026-07-01 P3 回归：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_clangd_adapter.py -q` -> `11 passed in 0.12s`。默认单 TU 模式保持不变，新增显式 background-index 开关测试。
- 2026-07-01 真实 ARM 实测（复用 vs 重建）：启动 `clangd --background-index=true`，cwd/compile dir 指向 `/home/linhao/Toolchain/codes/rw_arm`，打开真实 TU 后未触发 31s 重建；分片前后均为 3593 个 `.idx`、总大小 39911040 bytes、最新 mtime ns `1781072784911021003`，确认本次查询复用现有分片。
- 2026-07-01 真实 ARM 实测（索引 ready 时机）：只 initialize 不 open TU 时，`workspace/symbol(gst_element_set_state)` 轮询 12s 仍为 0；打开 `gst-launch.c` 后，`workspace/symbol` 在约 1.213s 返回 `gstelement.c` 命中，`find_references` 在约 5.266s 复现 389 refs。结论：P6 必须先 open/warm 一个 TU，再等待/轮询目标符号确认索引 ready。
- 2026-07-01 真实 ARM 实测（P6 API）：`CodeGraph(BuildConfig("arm", "/home/linhao/Toolchain/codes/rw_arm", background_index=True))` 下，`search_symbol("gst_element_set_state")` -> 1.638s，`status=OK`，`index_health=complete`，语义结果为 `gstelement.c:2951`；`get_definition` 从 `gst-launch.c:565` 调用点 -> 0.836s，`status=OK`，`index_health=complete`，语义结果为 `gstelement.h:1153`。`get_definition` 在该 C 工程里返回声明位置，单 TU/全局模式无差异；全局索引消费的实证来自 `search_symbol` 返回 source `.c` 定义与 P7 留底的 389 refs 对照。
- 2026-07-01 真实 ARM 补测（get_definition 全局索引对照）：扩大扫描 180 个真实 CDB 源文件/1702 个调用探针，先 warm 到 `workspace/symbol(gst_element_set_state)` ready（约 1 个 0.5s poll），再比较 `background_index=False` 与 `True`。确认 `get_definition` 自身会因全局索引从头文件声明跳到跨文件 `.c` 实现：例如 `gstbufferlist.c:91` 的 `gst_buffer_ref`，单 TU -> `gstbuffer.h:463`，全局 -> `gstbuffer.c:3014`；`gstbufferlist.c:35` 的 `gst_pad_push_list`，单 TU -> `gstpad.h:1515`，全局 -> `gstpad.c:4920`；`gstcontext.c:35` 的 `gst_element_set_context`，单 TU -> `gstelement.h:1016`，全局 -> `gstelement.c:3604`。本轮前 53 个有效探针即发现 10 个 `.c` 实现级差异，坐实 `get_definition` 代码路径已消费 P5 background-index；此前 `gst_element_set_state` 无差异只是该符号/位置恰好单 TU 已能解析到声明。
- 2026-07-01 P6 定向：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_api.py -q` -> `5 passed in 0.39s`；`tests/test_clangd_adapter.py` 已回归 `11 passed`。
- 2026-07-01 全量 gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `119 passed in 1.88s`；coverage -> `119 passed`，total 92%，`codegraph/api.py` 83%，`clangd_adapter.py` 100%；`.venv/bin/ruff check .` -> All checks passed；`.venv/bin/black --check .` -> 22 files unchanged；`.venv/bin/mypy codegraph` -> Success；`.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。
- 2026-07-01 Review BLOCKER 修复真实回归：`gstbufferlist.c:91` 的 `gst_buffer_ref`，`background_index=False` 下 `search_symbol` -> `UNRESOLVED/index_unknown`（不再 not_found），`get_definition` -> `UNRESOLVED/index_unknown`；`background_index=True` 且 sentinel=`gst_buffer_ref`/suffix=`gstbuffer.c` 下，`search_symbol` 1.577s -> `OK/complete`，语义结果 `gstbuffer.c:3014`，`get_definition` 1.576s -> `OK/complete`，语义结果 `gstbuffer.c:3014`。
- 2026-07-01 BLOCKER 修复后 gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_api.py -q` -> `10 passed in 0.41s`；`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `124 passed in 1.89s`；coverage -> `124 passed`，total 91%，`codegraph/api.py` 82%，`clangd_adapter.py` 100%；`.venv/bin/ruff check .` -> All checks passed；`.venv/bin/black --check .` -> 22 files unchanged；`.venv/bin/mypy codegraph` -> Success；`.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。
