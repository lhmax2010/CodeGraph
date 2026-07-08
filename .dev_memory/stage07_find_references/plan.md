# Stage 07 - find_references / Plan

## 目标
交付 `find_references` 端到端接口，复用 P6 已建立的 CodeGraph / prewarm / sentinel / warm
background-index 消费骨架，证明 CodeGraph 能在真实 ARM GBS 索引上返回跨 TU 引用集。

核心验收：在真实 `rw_arm` 3593 个 `.idx` 分片上，对 `gst_element_set_state` 复现
`389 refs / 62 files`，并返回带 `coverage.index_scope=indexed_project` 的结果，通过
`check_invariants` + `check_query_result_invariants`。

## 风险档
高风险，需三路 review。

理由：
- P7 是 CodeGraph 的核心价值证明，不只是新增一个 API。
- `find_references` 涉及全局索引 ready、跨 TU 覆盖、分页/total_hits、空结果诚实性。
- design v1.4.5/change_5 明确警示：background-index 下空 references 不能解释为“确认无引用”，
  且 `is_exhaustive_within_scope=True` 需要独立完整性证据。
- P6 曾连续暴露多层虚假否定/ready/窗口截断问题，P7 必须继承这些安全约束。

## 范围边界
做：
- `CodeGraph.find_references()` 与 module-level `find_references()` API。
- 复用 P6 `_warm_background_index()` / `CodeGraph.prewarm()` / sentinel + path suffix / health/scope guard。
- 调用 P3 `ClangdAdapter.find_references()`，不重写 LSP 协议层。
- `ReferenceResult` 端到端组装、`limit` / `offset` / `total_hits` 语义。
- 空 references 在 MVP background-index 下返回 `UNRESOLVED`，不产 not_found。
- 正结果不在 background-index 下声明 `is_exhaustive_within_scope=True`，除非后续实现给出独立完整性证据。
- 小型 fake/真实 clangd 单测 + 真实 ARM 查询级验收。

不做：
- 不做 `find_callers` / `find_callees`，那是 P8。
- 不做 MCP，P9 才做。
- 不做 clangd-indexer、逐 TU 台账、项目级负证明恢复。
- 不改 design.md；若发现 P7 契约矛盾，按 R1 输出 design issue。
- 不重写 `tools/verify_clangd.py` 或 LSP 客户端。

## 计划步骤
1. 审计 P6 API 与 P3 adapter 接缝：确认 `find_references` 需要的输入、输出、health/scope/ready 传递。
2. 设计 references total 语义：保留 adapter 原始返回总数，API 层按用户 `limit/offset` 分页并填
   `QueryResult.total_hits`，避免 adapter 提前分页后丢失 total。
3. 实现 `CodeGraph.find_references()`：校验 file/pos，创建 entity `QueryMeta`，用 P6 的 warm/ready
   机制启动 background-index clangd，调用 adapter references，按 ready 状态传 health/scope。
4. 实现 module-level `find_references()` 与 registry 行为，保持 `register_build_config()` 契约不变。
5. 安全约束测试：
   - bg=True ready+complete+空 references -> `UNRESOLVED`，非 not_found。
   - bg=False 或未 ready -> `UNRESOLVED/unknown`，不借 P5 complete 负证明。
   - positive references -> `OK/complete`，coverage 为 indexed_project，但不声明 exhaustive。
   - `limit/offset/total_hits` 正确，空页但 total>0 不落 not_found。
6. P3/P6 回归：现有 `search_symbol` / `get_definition` / adapter tests 不破。
7. 真机验收：
   - 复用 `/home/linhao/Toolchain/codes/rw_arm` 现有 3593 分片，不重建。
   - `gst_element_set_state` -> `389 refs / 62 files`。
   - 验证分片快照前后不变，响应秒级。
8. Gate：`.venv` 跑 pytest、coverage、ruff、black、mypy、compileall；记录到 progress/result。

## 依赖前置阶段
- P1：元数据、不变量、`ReferenceResult` 类型。
- P2：路由状态机、QR1-9、background-index not_found guard。
- P3：`ClangdAdapter.find_references()` 原始 LSP observation。
- P4：syntax helper，避免宏/伪位置误升。
- P5：真实 ARM background-index 分片与 index_health。
- P6：CodeGraph API skeleton、prewarm/sentinel/warm、health/scope guard、change_5 对齐。

## Baseline
- 分支：`phase/7-find-references`
- Baseline commit：`1ce3499 [Phase 6] docs: close e2e stage`
- Baseline gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 2.06s`

## 开工探测
- P5 ARM 分片仍在：`3593` 个 `.idx`，约 `47M`。
- CDB：`/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`，`1304` entries。
- 直接 adapter 探测：
  - 若只 warm/query 不充分，`gst_element_set_state` references 可退化为 `2 refs / 1 file`，说明 ready/warm
    方式必须被 P7 固化。
  - 使用 background-index、warm 真实 TU 后，对 `gstelement.c:2951` 定义点、
    `gstelement.h:1153` 声明点、`gstutils.c:2185` 调用点均复现 `389 refs / 62 files`。

