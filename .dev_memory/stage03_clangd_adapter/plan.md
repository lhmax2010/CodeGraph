# Stage 03 - Clangd Adapter / Plan

## 目标
启动 CodeGraph Phase 3：clangd 适配器。按 `docs/design.md` v1.4.3 §7 Phase 3 与 §10 引擎层 DoD 落地：
- 复用 `tools/verify_clangd.py` 的标准库 LSP 客户端能力，不重写 LSP 协议层。
- 封装 definition / references / callHierarchy 查询，实现 `EngineObservation` 协议。
- 产出“观察到的事实”：位置、引用、调用边、诊断、include-not-found/fatal 信息；不下可信度结论。
- LSP 调用必须有超时；超时或 clangd 错误向上暴露为适配器异常，供 P2 `route_engine_call()` 转成 `FAILED + IssueCode`。

## 范围边界
做：
- 新增 `codegraph/engines/clangd_adapter.py`，保持核心代码纯 stdlib。
- 复用/提取 `tools/verify_clangd.py` 中的 `LSPClient`、`path_to_uri`、诊断收集、请求超时模式；必要时只做最小兼容改造。
- 实现 `search_symbol`、`get_definition`、`find_references`、`find_callers`、`find_callees` 的 clangd observation 封装；其中 callers/callees 必须走 `textDocument/prepareCallHierarchy` + `callHierarchy/incomingCalls` / `outgoingCalls`。
- 把 clangd 返回的 LSP Location / LocationLink / CallHierarchy item/call 映射为 P1 类型：`LocationResult`、`ReferenceResult`、`CallEdgeResult`、`SymbolId`、`Range`、`Pos`。
- 收集 `textDocument/publishDiagnostics`，将 include-not-found 类诊断归入 `EngineDiagnostics.file_not_found`，其他硬错误归入 `fatal` 或 `soft`（最终分级实现前需按 clangd 诊断实际格式确认）。
- 用小型测试 CDB / 临时 C 文件做本机真实 clangd 集成测试；同时用假 LSP client 覆盖 timeout/error/callHierarchy unsupported 等 deterministic 单测。

不做：
- 不做 P2 路由可信度判断：不填 `Credibility`，不判断 resolved/relation/certainty/not_found。
- 不做 P4 tree-sitter、宏展开/预处理器位置判定、syntax helper、候选评分。
- 不做 P5 离线建库、index_health 判定、background-index 分片管理。
- 不做 P6 对外 API 编排；P3 只交付 adapter 与 `EngineObservationResult`。
- 不用 references+AST 推导调用图；callers/callees 只能使用 clangd callHierarchy。
- 不修改 `docs/design.md`；发现契约问题按 R1 登记 design change。

## 计划步骤
1. 梳理 `tools/verify_clangd.py` 的 LSP 客户端边界：initialize/initialized、didOpen、request timeout、diagnostics、shutdown、definition/references/callHierarchy 已有能力。
2. 设计 `clangd_adapter.py` 最小 API：配置 dataclass、adapter 生命周期、URI/位置转换、diagnostics 分类、LSP 结果 normalize helper。
3. 先写 fake-client 单测覆盖转换函数、超时传播、callHierarchy unsupported、不下可信度结论。
4. 实现 `get_definition`、`find_references` 的真实 LSP 调用，返回 `EngineObservationResult`。
5. 实现 `find_callers` / `find_callees` 的 callHierarchy 路径；clangd 不支持或返回错误时抛 `NotImplementedError` 或 adapter exception，由 P2 路由转 `CALLHIERARCHY_UNSUPPORTED` / `ENGINE_UNAVAILABLE`。
6. 实现 `search_symbol` 使用 `workspace/symbol` 或当前 verify asset 可支撑的 clangd symbol 查询能力；若发现 clangd 对小型 CDB 的语义不稳定，先停下报告方案，不用 tree-sitter 代替。
7. 建小型 fixture CDB，跑本机 clangd 18.1.3 集成测试，验证 definition/references/callHierarchy 能真实返回。
8. 跑 deterministic gate：pytest、ruff、black、mypy、必要 coverage；结果写入 progress。

## 依赖前置阶段
- 已完成并 Merge：stage01_metadata、stage02_routing。
- Phase 3 依赖 P1 的 `EngineObservation` 协议和 P1/P2 类型，不依赖 P4/P5/P6。

## Baseline（改前状态）
- Git baseline：`e87543d` (`[Phase 2] docs: close routing stage`)。
- 分支：从 `main@e87543d` 新建 `phase/3-clangd-adapter`。
- Baseline 测试命令：`PYTHONPATH=.:tools python3 -m pytest tests/ -q`
- Baseline 测试结果：`80 passed in 0.07s`。
- clangd 环境：`/usr/bin/clangd`，`Ubuntu clangd version 18.1.3 (1ubuntu1)`，`Features: linux+grpc`，`Platform: x86_64-pc-linux-gnu`。

## 风险档判断
Phase 3 风险档候选：高。

理由：
- P3 是项目第一次接真实外部引擎和子进程/LSP 通信，新增超时、进程生命周期、诊断异步、LSP schema 兼容等不确定性。
- callHierarchy 是硬要求，且不能用 references/AST 近似替代；不同 clangd 版本/小型 fixture 下可能有返回形状差异。
- P3 输出会喂给 P2 路由；一旦 adapter 混入可信度判断或误分类诊断，会污染后续 P6/P8。
- 缓解点：本机已安装 clangd 18.1.3；`tools/verify_clangd.py` 已有 PoC 真机验证过的 LSP 客户端资产；P3 可用小型 CDB 开发，不依赖 P5 全局索引。

## 当前暂停点
已完成开 stage 准备。实现前等待开发者确认风险档与 restate 计划。
