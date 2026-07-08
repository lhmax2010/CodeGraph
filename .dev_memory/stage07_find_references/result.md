# Stage 07 - find_references / Result

## 最终状态
已真机验收 / Review 通过 / 可 Merge。

复核记录（本次 review 由 Kimi Code CLI 执行，针对 commit `6ee54b6`）：
- UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `150 passed in 2.18s`
- 静态 gate：ruff / black --check / mypy codegraph / compileall / git diff --check 全绿
- 真机复现（默认 `warmup_file=None`，复用 P5 3593 分片，不重建）：
  - 连续 5 次 `find_references(gst_element_set_state, gstelement.c:2951)`：
    全部 `status=ok`, `index_health=complete`, `total_hits=389`, `semantic=381`, `candidates=8`,
    `files=62`，耗时 2.25–2.34s，稳定无波动。
  - `bg=False`：返回局部 2 refs，但 `status=ok`, `index_health=unknown`, `scope=current_tu`，
    无 `indexed_project` 谎标。
  - `index_ready_timeout=0`（cross-TU 未证明）：同样返回局部 2 refs，`current_tu/unknown`。
  - 索引分片验收前后不变：`(3593, 39911040)`。
- 结论：MAJOR 修复（A 默认路径稳定 389 + B 退化诚实降 current_tu）已修净；
  guard 已扩展到 status/semantic/candidates；空结果路径未受影响；P6 回归无破。

（上一轮 review 发现的 MAJOR：默认 warm query file 导致 2 refs 却标 `indexed_project`，
已在 `6ee54b6` 通过 query-specific ref-count stability + cross-TU evidence 修复。）

最终真机验收（2026-07-08，复用 P5 现有 3593 分片，不重建）：
1. **核心价值**：默认 `warmup_file=None`，连续 5 次
   `find_references(gst_element_set_state, gstelement.c:2951, limit=500)` 全部稳定：
   `status=ok`、`index_health=complete`、`total_hits=389`、`381 semantic + 8 candidates`、
   `62 files`、scope 仅 `indexed_project`、`negative_scope=none`、`is_exhaustive=False`；
   耗时 `2.371s / 2.354s / 2.373s / 2.300s / 2.339s`。
2. **scope 诚实**：`background_index=False` 同一查询返回局部 `2 refs / 1 file`，
   `status=ok`、`index_health=unknown`、scope 仅 `current_tu`、`is_exhaustive=False`；
   强制 `index_ready_timeout=0` + `warmup_file=query` 的 cross-TU 未证明路径同样为
   `2 refs / 1 file`、`current_tu/unknown`，没有 `indexed_project` 谎标。
3. **is_exhaustive 诚实**：默认 389 路径、bg=False 局部路径、timeout0 未证明路径的
   status/semantic/candidate credibility 均未声明 `is_exhaustive_within_scope=True`。
4. **候选诚实分层**：389 条中 `381` 条进入 semantic，`8` 条进入
   `consumer_warning=not_evidence` candidates；候选没有伪装成 semantic，也没有被丢弃。
5. **空结果诚实**：真实非符号位置 `gstelement.c:1:1` 查询返回
   `status=unresolved`、`index_health=unknown`、`total_hits=0`、0 semantic/0 candidates，
   notes 为 `fallback_disabled` + `index_unknown`，没有产出 `not_found`。
6. **复用不重建**：索引快照前后均为 `(3593, 39911040, 1781072784911021003)`。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 2.06s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `150 passed in 2.76s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ --cov=codegraph --cov-branch -q` -> `150 passed`，total `93%`，`codegraph/api.py` `94%`，`codegraph/engines/clangd_adapter.py` `100%`，`codegraph/routing.py` `95%`。
- 静态 gate：
  - `.venv/bin/ruff check .` -> All checks passed。
  - `.venv/bin/black --check .` -> 22 files unchanged。
  - `.venv/bin/mypy codegraph` -> Success: no issues found。
  - `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。
  - `git diff --check` -> 通过。
- 补测内容：
  - `CodeGraph.find_references()` + module-level `find_references()` registry。
  - `ReferenceResult` positive results: `status=OK`，`coverage.index_scope=indexed_project`，`is_exhaustive_within_scope=False`，`negative_scope=none`。
  - `limit/offset/total_hits`：adapter 保留 raw `total_results`，API 映射为 `QueryResult.total_hits`。
  - 空 references -> `UNRESOLVED`，非 not_found。
  - 默认 `warmup_file=None`：自动选择非 query、非 probe suffix 的 warmup TU，避免 query TU 单独命中误判 ready。
  - references ready：对同一个 `find_references` 查询轮询到“连续两次引用集签名一致且包含跨 TU 证据”才允许 `indexed_project/complete`。
  - bg=False / warm 不足 / cross-TU 未证明 -> 可返回局部 positive refs，但必须 `current_tu/unknown`，不假装项目级完整。
  - P6 回归：search/definition/prewarm/sentinel 现有测试继续通过。

## 真机 ARM / P5 全局索引复现
- 环境：`clangd 18.1.3`；真实 ARM CDB `/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`；复用现有 P5 索引目录 `3593` 个 `.idx`，不重建。
- 查询：`gst_element_set_state`，query file `gstelement.c`，zero-based pos `[2950, 0]`；默认 `warmup_file=None`；sentinel=`gst_element_set_state`，suffix=`gstelement.c`。
- 索引快照：验收前 `(3593, 39911040, 1781072784911021003)`，验收后相同。
- `find_references` 默认路径连续 5 次：全部 `status=OK`，`index_health=complete`，`total_hits=389`，返回 `389 ReferenceResult / 62 files`；耗时约 `2.371s / 2.354s / 2.373s / 2.300s / 2.339s`。
- 诚实性形状：
  - `semantic_results=381`。
  - `syntactic_candidates=8`，均为 `consumer_warning=not_evidence`，原因是 P2/P4 盲区护栏保守降级；样例：`gsturidownloader.c:627`、`gsturidownloader.c:652`、`gstdecodebin3.c:2187`、`gst-launch.c:1288`。
  - semantic + candidate 全部为 `ReferenceResult`，全部 `index_scope=indexed_project`，全部 `is_exhaustive_within_scope=False`，全部 `negative_scope=none`。
- 安全底线：
  - bg=False 同一查询 -> `status=OK`，`index_health=unknown`，`total_hits=2`，`2 semantic / 0 candidates`，`1 file`，scope 仅 `current_tu`，`is_exhaustive=False`；这是诚实的单 TU 局部 positive，不是项目级覆盖。
  - `index_ready_timeout=0` + `warmup_file=query` 同一查询 -> `status=OK`，`index_health=unknown`，`total_hits=2`，`2 semantic / 0 candidates`，`1 file`，scope 仅 `current_tu`，`is_exhaustive=False`；这是 cross-TU 未证明时的真机退化路径。
  - 真实非符号位置 `gstelement.c:1:1` -> `UNRESOLVED/unknown`，`total_hits=0`，0 semantic/0 candidates，notes 为 `fallback_disabled` + `index_unknown`。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`1ce3499 [Phase 6] docs: close e2e stage`。
- 当前分支：`phase/7-find-references`。
- 对应 Git Commit：本轮实现提交 `[Phase 7] feat: wire find_references e2e`，review MAJOR 修复提交 `[Phase 7] fix: stabilize references readiness and scope honesty`（hash 见分支 HEAD）。

## 遗留问题 / 风险
- P7 继承 change_5 诚实性约束：background-index 下空 references 不能产 not_found。
- P7 不应在 background-index 下声明 `is_exhaustive_within_scope=True`，除非实现独立完整性证据。
- P7 真机核心验收已复现默认路径 `warmup_file=None` 下 `gst_element_set_state` 的 `389 refs / 62 files`；其中 8 条因盲区护栏为 `not_evidence` candidates，不作为 semantic evidence。
- P7 references ready 现在用 query-specific ref-count stability；若未来 clangd 行为变化导致无法证明 cross-TU，B 兜底会把结果标为 `current_tu/unknown`，避免 `2 refs + indexed_project` 的 scope 失真。
- [P7 review 重点] 确认 381 semantic + 8 not_evidence candidates 的验收口径是否符合“389 positive refs 但不保证全部”的诚实模型；不要为了凑 389 semantic 绕过 P2/P4 盲区护栏。
- [后续待留意] query-specific stability 判据仍存在理论局限：若 clangd 在中间 partial set 上连续两次返回同一跨 TU 子集、随后才加载更多分片，P7 可能把该 positive 子集标为 `indexed_project`。这不构成 P7 blocker：`is_exhaustive=False` 明确不声称“这就是全部引用”，且 B 兜底保证未证明 cross-TU 时降为 `current_tu/unknown`。二期 clangd-indexer 若提供精确 load-complete / per-TU ledger 信号，可从根上替代该启发式。
- [后续待留意] `engine_limit` vs clangd 实际 cap 的截断判据对齐：P6 search_symbol 的截断 guard 仍应在后续 harden，避免依赖当前 clangd 100-cap 巧合。
- [后续待留意] P3 `diagnostics_wait=0.5s` 在 broken / 大型 TU 上仍可能漏报 diagnostics；P7 未覆盖 broken TU，后续真机场景继续验证。
- [后续待留意] sentinel 配置错误目前主要表现为保守降级/等待超时；后续可加 warning，让调用方更容易发现配置错符号或错 suffix。
- [后续待留意] 空 `find_references` 目前会轮询到 `index_ready_timeout` 才返回 `UNRESOLVED/unknown`；后续可加 early-exit：引用集稳定为空时提前返回，避免无意义等待。
- [后续待留意] 冷启动首查延迟存在波动：Codex 复跑时第 1 次约 `15.7s`、后续约 `2.3s`。P7 热态功能验收数据成立；若未来写性能 SLA，应另开冷态/性能验收口径。
- [后续待留意] `codegraph/api.py` 覆盖率已达 94%，但部分异常分支仍可后续补测。

## 下一阶段计划
- P7 已过 review 与真机验收，等待用户核对后按收尾流程 merge / checkpoint。

## Merge Gate 复核（2026-07-08，针对 `cd009c2`）
- 执行者：Kimi Code CLI
- UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `150 passed in 2.94s`
- 静态 gate：ruff / black --check / mypy codegraph / compileall / git diff --check 全绿
- Spot-check 真机复现：
  - 默认 `warmup_file=None`：`389 refs / 62 files / 381 semantic + 8 candidates / OK/complete/indexed_project / is_exhaustive=False`
  - `bg=False`：`2 refs / current_tu / unknown`
  - 真实非符号位置：`UNRESOLVED/unknown/total_hits=0`
- 结论：result.md 六项验收数据自洽、与上轮 review 复现一致，P7 满足 merge 条件。
