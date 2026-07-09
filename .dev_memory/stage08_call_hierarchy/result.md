# Stage 08 - call_hierarchy / Result

## 最终状态
待 Review。

## 测试情况
- Baseline：`main@3bad237`，`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，150 passed in 7.06s。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，158 passed in 2.12s。
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

## PR 与代码
- PR 链接：待创建。
- 对应 Git Commit：未提交。

## 遗留问题 / 风险
- P8 需异构多路 review，重点看 call-edge ready 的 3 次稳定策略是否足够、是否需要进一步抽象成 P7/P8 共用策略。
- `find_callees` 在当前 clangd 18.1.3 上只能诚实 FAILED；clangd 20+ 支持 outgoingCalls 后同一路径应自动可用，需二次真机验收。
- callHierarchy positive 结果仍是 background-index 观察事实，不声明穷尽；消费者不得把结果当完整调用图。
- 空结果诚实性：prepare 定位不到与 located-but-empty 目前都不会声明“确实没有调用者/被调用者”，API 返回 `UNRESOLVED`，`negative_scope=none`，`is_exhaustive=False`。

## 下一阶段计划
- 通过 P8 review 后，按 review 修复问题并做最终真机验收。
