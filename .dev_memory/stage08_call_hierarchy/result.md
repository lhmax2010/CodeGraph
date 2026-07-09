# Stage 08 - call_hierarchy / Result

## 最终状态
已真机验收 / Review 通过 / 可 Merge。

Merge Gate 复核（2026-07-08，针对 `86deb8c`）：
- 执行者：Kimi Code CLI
- UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `158 passed in 2.14s`
- 静态 gate：ruff / black --check / mypy codegraph / compileall / git diff --check 全绿
- Spot-check 真机复现：
  - `find_callers(gst_element_set_state)`：`387` total / `379 semantic + 8 candidates` / `62 caller files` / `OK/complete/indexed_project` / `is_exhaustive=False`
  - `find_callers(gst_object_unref)`：`2951` total / `900 semantic + 100 candidates`（limit=1000）/ `184 caller files` / `OK/complete/indexed_project` / `is_exhaustive=False`
  - `find_callees(gst_element_set_state)`：`FAILED` + `CALLHIERARCHY_UNSUPPORTED`，无 fallback
  - `find_callers(gst_element_set_state, bg=False)`：局部 `1 ref` / `current_tu/unknown`
- 结论：P8 callers 诚实完整、callees 诚实 FAILED、located-vs-empty 不虚假否定，满足 merge 条件。

P7/P8 stability backport 复核（2026-07-09，P8 review 后追加）：
- 变更：P7 `find_references` 与 P8 call hierarchy 统一使用
  `_wait_for_stable_cross_tu_observation()` + `_STABLE_MATCHES=3`；P8 保守度不降，P7 从 2 次稳定升到 3 次稳定。
- UT / gate：`tests/test_api.py` -> `42 passed`；全套
  `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `159 passed in 2.44s`；
  coverage -> `159 passed`，total `93%`，`codegraph/api.py` `95%`；ruff / black --check /
  mypy codegraph / compileall / git diff --check 全绿。
- P7 真机硬门：默认 `warmup_file=None`，`gst_element_set_state` references 连续 3 次均为
  `status=ok`、`index_health=complete`、`total_hits=389`、`381 semantic + 8 candidates`、
  `62 files`、scope `indexed_project`、`is_exhaustive=False`；耗时 `2.885s / 2.893s / 2.862s`。
- P8 真机硬门：`find_callers(gst_element_set_state)` 仍 `387` total /
  `379 semantic + 8 candidates` / `62 caller files` / `OK/complete/indexed_project` /
  `is_exhaustive=False`；`find_callers(gst_object_unref)` 仍 `2951` total /
  `900 semantic + 100 candidates`（limit=1000，本次页内 `254 caller files`）/ `OK/complete/indexed_project` /
  `is_exhaustive=False`；`find_callees(gst_element_set_state)` 仍 `FAILED + CALLHIERARCHY_UNSUPPORTED`。
- 索引快照前后不变：`(3593, 39911040, 1781072784911021003)`，未重建。

## 测试情况
- Baseline：`main@3bad237`，`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，150 passed in 7.06s。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，159 passed in 2.44s。
- 定向回归：`tests/test_api.py` 覆盖 callers/callees API、unsupported、empty unresolved、scope honesty、短平台期、方向/relation、non-exhaustive guard；`tests/test_clangd_adapter.py` 覆盖 callHierarchy total_results。
- 静态：
  - `PYTHONPATH=.:tools .venv/bin/python -m ruff check .`：passed。
  - `PYTHONPATH=.:tools .venv/bin/python -m black --check .`：passed。
  - `PYTHONPATH=.:tools .venv/bin/python -m mypy codegraph`：passed。
  - 说明：完整 `mypy codegraph tests` 仍有既有 tests typing debt（未作为本阶段修复范围）。

## 真机验证
- 环境：Ubuntu clangd 18.1.3；rw_arm background-index 3593 `.idx`，快照前后 `(3593, 39911040, 1781072784911021003)` 不变，未重建。
- `find_callers("gst_element_set_state")`：
  - `status=OK`，`index_health=complete`，`index_scope=indexed_project`，`total_hits=387`。
  - `semantic_results=379`，`syntactic_candidates=8`，所有 credibility `is_exhaustive_within_scope=False`。
  - 跨 TU caller files 包含多个 C 文件；候选保留为 `not_evidence`，不伪装 semantic。
  - 语义自查：裸 adapter 单层 `callHierarchy/incomingCalls` 轮询为 `1 -> 3 -> 387 -> 387...`；387 是 clangd 一层 direct incoming callers 稳定结果，非递归/传递展开。
- `find_callers("gst_object_unref")`：
  - `status=OK`，`index_health=complete`，`index_scope=indexed_project`，`total_hits=2951`。
  - `limit=1000` 页内 `semantic_results=900`，`syntactic_candidates=100`，`is_exhaustive_within_scope=False`。
- `find_callees("gst_element_set_state")`：
  - 当前 clangd 18.1.3 `callHierarchy/outgoingCalls` 缺失，返回 `status=FAILED`，notes 包含 `CALLHIERARCHY_UNSUPPORTED`；无 semantic/candidate 结果。
- P7 backport 回归：
  - 默认 `warmup_file=None` 的 `find_references("gst_element_set_state")` 连续 3 次稳定 `389 refs / 62 files`，确认 3 次稳定没有改坏已 merge 的 P7 核心价值兑现。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- 对应 Git Commit：当前 WIP 待用户核对后提交。

## 遗留问题 / 风险
- P8 需异构多路 review，重点看 P7/P8 共用 `_STABLE_MATCHES=3` 是否保持 P7 389/62 与 P8 387/2951 的价值兑现。
- `find_callees` 在当前 clangd 18.1.3 上只能诚实 FAILED；clangd 20+ 支持 outgoingCalls 后同一路径应自动可用，需二次真机验收。
- callHierarchy positive 结果仍是 background-index 观察事实，不声明穷尽；消费者不得把结果当完整调用图。
- 空结果诚实性：prepare 定位不到与 located-but-empty 目前都不会声明“确实没有调用者/被调用者”，API 返回 `UNRESOLVED`，`negative_scope=none`，`is_exhaustive=False`。
- 结转不改：空结果会 poll 满 timeout 才返回 unresolved；更长 plateau 仍有理论残差（但 `is_exhaustive=False` + scope 兜底保证不作完整性声明）；stability 可配置化留后；P6/P7 结转的 sentinel warning、diagnostics_wait broken TU、api.py 异常分支覆盖仍留后续 harden。

## 下一阶段计划
- 通过 P8 review 后，按 review 修复问题并做最终真机验收。
