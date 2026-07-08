# Stage 07 - find_references / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：P7 复用 P6 background-index ready/prewarm/sentinel 骨架，不新建 LSP/prewarm 路径。
  - 原因：P6 已经为 search/definition 修过多层 ready 与虚假否定问题；P7 的风险是把同一套可靠消费方式扩到 references。
  - 排除的方案：重新封装 clangd references 或用 `verify_clangd.py` 单独跑查询；这会绕开 P6 安全逻辑。
- 决策：P7 默认高风险，需三路 review。
  - 原因：核心验收是 389 refs/62 files，且涉及 coverage/total_hits/空结果诚实性。
  - 排除的方案：按普通 API 增量处理；风险低估会重复 P6 的虚假否定问题。

## 改动摘要
- 文件/模块：
  - 待实现：`codegraph/api.py` 增加 `find_references`。
  - 待评估：`codegraph/engines/protocol.py` / `clangd_adapter.py` 如何保留 references raw total。
  - 待补测：`tests/test_api.py`、`tests/test_clangd_adapter.py`、必要时 `tests/test_phase2_routing.py`。

## 进度日志
- 2026-07-08 开 P7 分支 `phase/7-find-references`，baseline commit `1ce3499`。
- 2026-07-08 baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 2.06s`。
- 2026-07-08 真机探测：`rw_arm` 现有 3593 个 `.idx`、47M；CDB 1304 entries。直接 adapter 在 background-index + 正确 warm 后，`gst_element_set_state` 于 `.c` 定义点、`.h` 声明点、真实调用点均复现 `389 refs / 62 files`。一次不充分 warm/query 的探测只返回 `2 refs / 1 file`，说明 P7 必须复用并固定 P6 ready/warm 机制。
- 2026-07-08 P7 实现决策：`find_references` ready 前不调用/不返回局部 references，避免把单 TU 的 2 条误包装成跨 TU 能力；只有 `_warm_background_index()` 证明当前 clangd ready 后，才把 references 作为 semantic positive 返回。bg=False / warm 不足统一 `UNRESOLVED/unknown`。
- 2026-07-08 P7 穷尽性决策落代码：`routing._positive_coverage()` 显式构造 `is_exhaustive_within_scope=False` / `negative_scope=none`；`CodeGraph.find_references()` 额外 fail-loud 检查 background-index references 不得声明 exhaustive。389/62 只表达“找到这些引用”，不表达“全部引用”。
- 2026-07-08 P7 total 语义：`EngineObservationResult` 增加 `total_results`，`ClangdAdapter.find_references()` 在本地分页前记录 raw references 总数；API 将其映射为 `QueryResult.total_hits`，避免 page 长度冒充 total。
- 2026-07-08 定向测试：`tests/test_api.py` -> `29 passed`；`tests/test_clangd_adapter.py` -> `13 passed`；`tests/test_phase2_routing.py tests/test_phase1_metadata.py` -> `35 passed`。覆盖 positive non-exhaustive、空 references unresolved、未 ready/bg=False 不返回局部 refs、module-level registry、adapter total_results。
- 2026-07-08 真机首轮触发 P7 版 warm 坑：`CodeGraph.find_references()` 机械传 query file 给 `_warm_background_index()`，覆盖了 config.warmup_file；对 `gst_element_set_state` 定义文件 warm 后只返回 `2 refs / 1 file`，尽管 prewarm ready=True。修正为 references 查询优先使用 `config.warmup_file`，未配置时才退回 query file，并加单测锁定 warmup_file 优先。
- 2026-07-08 P7 核心真机验收通过（复用现有 3593 分片，不重建）：`CodeGraph.find_references(gst_element_set_state @ gstelement.c:2951)`，配置 `warmup_file=gstutils.c`，prewarm ready=True 1.411s，query 2.231s，`status=OK`，`index_health=complete`，`total_hits=389`，返回 `389 ReferenceResult / 62 files`。其中 381 条为 semantic_results，8 条因盲区护栏降为 `not_evidence` candidates（如 `gsturidownloader.c:627`、`gst-launch.c:1288`）；所有返回项 `index_scope=indexed_project`、`is_exhaustive_within_scope=False`、`negative_scope=none`，索引快照前后 `(3593, 39911040, 1781072784911021003)` 不变。
- 2026-07-08 P7 真机安全底线：同一符号 bg=False -> `UNRESOLVED/unknown`、0 semantic/0 candidates；warm_not_ready（`index_ready_timeout=0`）-> `UNRESOLVED/unknown`、0 semantic/0 candidates。确认不返回局部 2 条、不借 complete 健康度假装完整。
- 2026-07-08 P7 gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `146 passed in 2.17s`；coverage -> `146 passed`，total `93%`，`codegraph/api.py` `92%`，`codegraph/engines/clangd_adapter.py` `100%`，`codegraph/routing.py` `95%`；ruff/black/mypy/compileall/diff-check 全绿。
