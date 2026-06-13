# Stage 02 - Routing / Plan

## 目标
启动 CodeGraph Phase 2：路由判定核心 + QueryResult 容器校验。按 `docs/design.md` v1.4.2 §7 Phase 2 与 §4.4 落地：
- 实现两层路由状态机：引擎异常、clangd 非空结果可信/降级、空结果 not_found/unresolved 三分。
- 实现降级真值表与混合结果处理：可信结果进 `semantic_results`，不可信结果降级进 `syntactic_candidates`，不丢弃。
- 实现 `check_query_result_invariants()`，覆盖 QR1-9，并在路由返回前强制调用。
- 实现四道护栏的触发与放置逻辑；护栏3 只读 `relevance_score` 做阈值过滤。

## 范围边界
做：
- 新增/扩展 `codegraph/routing.py`，实现 P2 路由核心与容器校验。
- QR1-9 全部进入 `check_query_result_invariants()`，并测试矛盾容器被拒。
- QR1 必须按双向 `status==OK ⟺ len(semantic_results)>0` 实现：既拒绝 `OK` 无语义结果，也拒绝有语义结果却标 `UNRESOLVED`/`NOT_FOUND` 等非 OK 状态。
- 路由所有返回路径强制过单条 `check_invariants()` 与容器 `check_query_result_invariants()`。
- 用 P1 的 `EngineObservation` / `SyntacticProvider` 协议和测试桩开发，不依赖 P3/P4 真实适配器。
- 护栏3 只按阈值过滤：精确查询阈值 20，`search_symbol` 阈值 15；分数由 Mock/桩注入。
- QR7 按 v1.4.2 执行：候选 `relation ∈ {may, n/a}`，entity 候选用 `n/a`，relation 候选用 `may`，绝不 `must`。
- §4.4 降级规则：缺要素1/2/4 降级入候选；缺要素1 带 `DEPENDENCY_INCOMPLETE`，缺要素4 带 `SYMBOL_AMBIGUOUS`；全部不可信时返回 `UNRESOLVED`，不进入 not_found。
- 状态机必须把“clangd 返回了但不可信”和“clangd 返回空”分成两个代码分支：非空结果先走降级真值表，全不可信返回 `UNRESOLVED`；只有返回空才进入可能 `NOT_FOUND` 的空结果分支。

不做：
- 不实现真实 clangd adapter（P3）。
- 不实现真实 tree-sitter adapter、宏展开 helper、relevance_score 评分算法（P4）。
- 不实现 search/get_definition 等对外接口端到端（P6）。
- 不实现离线建库/index_health 产出（P5）。
- 不提前做 P7/P8/P9 或 §3.5 二期清单。
- 不修改 `docs/design.md`；发现契约问题按 R1 输出 `[DESIGN_ISSUE]` 并登记 change。

## 计划步骤
1. 读取现有 P1 类型、factories、credibility 与 engine protocol，确认可复用的构造方式。
2. 设计 `routing.py` 的最小 API：容器校验函数、路由入口、内部分类/降级 helper，保持纯 stdlib。
3. 先实现并测试 `check_query_result_invariants()` QR1-9，覆盖每条 QR 的拒绝与紧邻合法组合。
4. 用桩实现分支0 引擎异常：返回 `FAILED`，不触发 syntactic fallback，双校验不可绕过。
5. 实现 clangd 非空结果分支：四要素判定、缺 1/2/4 降级候选、要素3 只调 coverage、混合结果不丢弃。
6. 实现空结果分支：只有满足 exhaustive/依赖/index/盲区条件时 `NOT_FOUND`；否则 `UNRESOLVED`，按查询类型和 allow flag 触发候选。
7. 实现 syntactic fallback 候选放置、`not_evidence`、QR7 relation `{may,n/a}`、阈值过滤和 suppress note。
8. 补全不可绕过测试、回归旧 28 测试和全套测试。
9. 跑 deterministic gate：ruff、black、mypy、pytest、coverage；结果写入 progress/review artifact。

## 测试桩场景清单
P2 测试桩必须能构造以下 clangd observation 场景，确保降级真值表逐项被测到：
- 缺要素1：依赖不完整，结果降级为 clangd/syntactic 候选，并记录 `DEPENDENCY_INCOMPLETE`。
- 缺要素2：宏展开/预处理盲区影响结果，结果降级为 clangd/syntactic 候选，`blind_spot_affects_result=True`。
- 缺要素4：符号身份歧义，结果降级为 clangd/syntactic 候选，并记录 `SYMBOL_AMBIGUOUS`。
- 全部不可信：clangd 返回非空，但每条结果都缺 1/2/4 中至少一项，最终 `UNRESOLVED`，不得进入 `NOT_FOUND`。
- 混合结果：部分可信进入 `semantic_results`，部分不可信降级入 `syntactic_candidates`，不丢弃。
- clangd 返回空：只在空结果分支内判断 `NOT_FOUND` vs `UNRESOLVED`。
- 引擎异常：返回 `FAILED`，不触发 tree-sitter 兜底。

## 依赖前置阶段
- 已完成并 Merge：stage01_metadata。
- Phase 2 只依赖 P1 的元数据、数据结构、factories、`EngineObservation` / `SyntacticProvider` 协议。
- 不依赖 P3/P4/P5 具体实现；真实集成等待 P6。

## Baseline（改前状态）
- Git baseline：`9e1157f` (`[Phase 1] docs: mark metadata stage merged`)。
- 分支：从 `main@9e1157f` 新建 `phase/2-routing`。
- Baseline 测试命令：`PYTHONPATH=.:tools python3 -m pytest tests/ -q`
- Baseline 测试结果：`67 passed in 0.07s`。

## 风险档判断
Phase 2 风险档候选：高。

理由：
- P2 是路由状态机和 QR1-9 容器契约的交叉层，错误会直接污染后续 P6-P9 的外部行为。
- 状态组合多：异常、非空可信、非空降级、混合结果、空结果、fallback、阈值过滤、notes 与 credibility 双校验都要组合测试。
- QR7 已经经历 R1 设计修订，必须按 `{may, n/a}` 实现，不能回到旧 `==may`。
- 缓解点：仍是纯 Python/stdlib，可用 P1 协议桩隔离测试，不需要真实 clangd/tree-sitter/索引环境。

## 当前暂停点
已完成开 stage 准备。实现前等待开发者确认风险档与 restate 计划。
