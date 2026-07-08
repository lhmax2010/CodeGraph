# Stage 07 - find_references / Result

## 最终状态
待 Review。P7 `find_references` 已实现，核心真机验收已复现 `gst_element_set_state`
`389 refs / 62 files`；按用户要求，核心价值 + change_5 诚实性修改需过用户异构多路 review，
review 通过后才能 merge。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 2.06s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `146 passed in 2.17s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `146 passed`，total `93%`，`codegraph/api.py` `92%`，`codegraph/engines/clangd_adapter.py` `100%`，`codegraph/routing.py` `95%`。
- 静态 gate：
  - `.venv/bin/ruff check .` -> All checks passed。
  - `.venv/bin/black --check .` -> 22 files unchanged。
  - `.venv/bin/mypy codegraph` -> Success: no issues found。
  - `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。
- 补测内容：
  - `CodeGraph.find_references()` + module-level `find_references()` registry。
  - `ReferenceResult` positive results: `status=OK`，`coverage.index_scope=indexed_project`，`is_exhaustive_within_scope=False`，`negative_scope=none`。
  - `limit/offset/total_hits`：adapter 保留 raw `total_results`，API 映射为 `QueryResult.total_hits`。
  - 空 references -> `UNRESOLVED`，非 not_found。
  - bg=False / warm 不足 -> `UNRESOLVED/unknown`，不返回局部 refs、不假装完整。
  - P6 回归：search/definition/prewarm/sentinel 现有测试继续通过。

## 真机 ARM / P5 全局索引复现
- 环境：`clangd 18.1.3`；真实 ARM CDB `/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`；复用现有 P5 索引目录 `3593` 个 `.idx`，不重建。
- 查询：`gst_element_set_state`，query file `gstelement.c`，zero-based pos `[2950, 0]`；`warmup_file=gstutils.c`；sentinel=`gst_element_set_state`，suffix=`gstelement.c`。
- 索引快照：验收前 `(3593, 39911040, 1781072784911021003)`，验收后相同。
- Prewarm：`ready=True`，`1.411s`。
- `find_references`：`2.231s`，`status=OK`，`index_health=complete`，`total_hits=389`，返回 `389 ReferenceResult / 62 files`。
- 诚实性形状：
  - `semantic_results=381`。
  - `syntactic_candidates=8`，均为 `consumer_warning=not_evidence`，原因是 P2/P4 盲区护栏保守降级；样例：`gsturidownloader.c:627`、`gsturidownloader.c:652`、`gstdecodebin3.c:2187`、`gst-launch.c:1288`。
  - semantic + candidate 全部为 `ReferenceResult`，全部 `index_scope=indexed_project`，全部 `is_exhaustive_within_scope=False`，全部 `negative_scope=none`。
- 安全底线：
  - bg=False 同一查询 -> `UNRESOLVED/unknown`，`total_hits=0`，0 semantic/0 candidates。
  - warm_not_ready（`index_ready_timeout=0`）同一查询 -> `UNRESOLVED/unknown`，`total_hits=0`，0 semantic/0 candidates。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`1ce3499 [Phase 6] docs: close e2e stage`。
- 当前分支：`phase/7-find-references`。
- 对应 Git Commit：本轮实现提交 `[Phase 7] feat: wire find_references e2e`（hash 见分支 HEAD）。

## 遗留问题 / 风险
- P7 继承 change_5 诚实性约束：background-index 下空 references 不能产 not_found。
- P7 不应在 background-index 下声明 `is_exhaustive_within_scope=True`，除非实现独立完整性证据。
- P7 真机核心验收已复现 `gst_element_set_state` 的 `389 refs / 62 files`；其中 8 条因盲区护栏为 `not_evidence` candidates，不作为 semantic evidence。
- [P7 review 重点] 确认 381 semantic + 8 not_evidence candidates 的验收口径是否符合“389 positive refs 但不保证全部”的诚实模型；不要为了凑 389 semantic 绕过 P2/P4 盲区护栏。

## 下一阶段计划
- 过用户异构多路 review；review 通过后再按收尾流程 merge / checkpoint。
