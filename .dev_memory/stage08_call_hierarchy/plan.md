# Stage 08 - call_hierarchy / Plan

## 目标
实现 `find_callers` / `find_callees` 端到端调用关系查询，复用 P3 clangd callHierarchy observation、P2 routing、P1 credibility、P4 syntax helper、P5 background-index 与 P6/P7 API 骨架。

## 风险档
高风险。

原因不是代码规模，而是真实引擎能力与诚实性边界都在核心路径上：P8 依赖 clangd `callHierarchy`，且必须复用 P7 的 ready/scope/exhaustive/empty 四类诚实性模式。2026-07-08 预探测显示 Ubuntu clangd 18.1.3 在 rw_arm 上 `prepareCallHierarchy` 与 `incomingCalls` 可用，但标准 LSP `callHierarchy/outgoingCalls` 返回 `method not found`，因此 `find_callees` 可能只能按设计降级为 `FAILED + CALLHIERARCHY_UNSUPPORTED`，交付形态需开工前确认。

## 范围边界
做：
- 库 API 与模块级 API：`find_callers` / `find_callees`。
- 使用 LSP `textDocument/prepareCallHierarchy` 后接 `callHierarchy/incomingCalls` / `callHierarchy/outgoingCalls`。
- 用 `CallEdgeResult` 无损承载调用边，保留 `from_symbol` / `to_symbol` / `call_site` 与方向。
- relation 查询使用 `query.kind="relation"`；语义精确调用边为 `must`，降级候选为 `may` + `consumer_warning="not_evidence"`。
- 复用 P7 的 readiness、scope、non-exhaustive 与 empty-result 诚实策略。
- callHierarchy 不支持时返回 `FAILED + CALLHIERARCHY_UNSUPPORTED`，不触发 tree-sitter / references+AST 兜底。

不做：
- 不做 `get_impact`。
- 不做 MCP server。
- 不用 references + AST 自行推导调用图。
- 不实现二期 clangd-indexer、逐 TU 台账或 not_found 恢复。

## P8 诚实性策略
- ready 判据：call hierarchy 查询采用 query-specific stability + cross-TU evidence。不能只靠 sentinel 或打开 query file 就认为全局索引 ready。
- scope 诚实：跨 TU 证据未证明时只允许 `current_tu/unknown`，不得标 `indexed_project/complete`。
- is_exhaustive 诚实：background-index 下 callers/callees positive 结果恒 `is_exhaustive_within_scope=False`；增加 fail-loud guard，覆盖 status、semantic results、candidates。
- 空结果诚实：`prepareCallHierarchy` 定位不到、索引未 ready、或 call 边为空，都不得在 MVP background-index 下声明 not_found 或“确实没有调用者/被调用者”；返回 `UNRESOLVED`，必要时保留结构化 note。

## 计划步骤
1. 复核 design.md v1.4.5 的 §4.1.1、CallEdgeResult、§4.4、INV14d、INV21、§7 Phase 8，并确认 P7 result 的结转项不被 P8 误用。
2. 真机确认 clangd 18.1.3 callHierarchy 能力：`prepareCallHierarchy`、`incomingCalls`、`outgoingCalls`、跨 TU incoming edge。
3. 等用户确认交付形态，尤其是当前 `outgoingCalls` unsupported 时 `find_callees` 是否按设计交付 `FAILED + CALLHIERARCHY_UNSUPPORTED`。
4. 实现 API 编排：复用 P7 prewarm/stability/scope helpers，必要时抽出 edge 版本 helper，避免复制出漂移逻辑。
5. 补单元测试：CallEdgeResult 方向与 relation、unsupported、空结果 unresolved、局部退化 current_tu/unknown、background-index non-exhaustive guard、P1/P2/P6/P7 回归。
6. 跑全套 `.venv` 测试与静态 gate；有真机环境时做 rw_arm call hierarchy 验收。

## 依赖前置阶段
- stage07_find_references 已 Merge，baseline commit 为 `3bad237`。
- baseline 测试：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，150 passed in 7.06s。

## DoD
- `find_callers` / `find_callees` 只走 LSP callHierarchy，不实现替代调用图算法。
- `CallEdgeResult` 方向正确，降级候选无损。
- background-index 下不声明调用边结果穷尽，不从空结果产 not_found。
- unsupported 路径结构化失败且不兜底。
- P1-P7 全回归通过。
