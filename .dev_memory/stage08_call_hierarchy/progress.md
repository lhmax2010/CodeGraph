# Stage 08 - call_hierarchy / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：P8 开工前先做真实 clangd callHierarchy 能力探测，再确认实现形态。
  - 原因：design.md §6 R-技6 明确 callHierarchy 支持差异是 P8 头号风险。
  - 排除的方案：不先假定 callers/callees 都可用；不先写 references+AST 兜底。
- 决策：采用交付形态 A：`find_callers` 正常交付；`find_callees` 接标准 LSP `callHierarchy/outgoingCalls`，当前 clangd 18.1.3 返回 `method not found` 时诚实 `FAILED + CALLHIERARCHY_UNSUPPORTED`。
  - 原因：本地同一个 `prepareCallHierarchy` item 喂给 incoming 成功、喂给 outgoing 失败；LLVM 20.1 release notes 说明 outgoing calls 是 clangd 20 新增能力。
  - 排除的方案：不做 references+AST 兜底；不把 outgoing 缺失误报成整个 callHierarchy 不支持。
- 决策：P8 call-edge ready 比 P7 references 更保守，要求 3 次连续同签名稳定且有跨 TU edge 证据，才把 scope/health 提升到 `indexed_project/complete`。
  - 原因：真机 `gst_object_unref` 暴露短平台期：裸 adapter 会出现 8 → 52 → 2951 的渐进加载；两次稳定可能早退并让 `total_hits` 失真。
  - 排除的方案：不靠固定 sleep；不把未稳定结果标成 `indexed_project/complete`。
- 决策：located-but-empty 与 prepare 定位不到在 MVP background-index 下都返回 `UNRESOLVED`。
  - 原因：无逐 TU 台账时，空 incoming 不能区分“确实无调用者”和“调用者所在 TU 未被索引/未加载”；继承 change_5/P7 的负证明诚实性。
  - 排除的方案：不产 not_found；不声明“确实没有调用者/被调用者”。

## 改动摘要
- `.dev_memory/INDEX.md`
  - 将当前活跃 stage 设为 `stage08_call_hierarchy`。
- `.dev_memory/stage08_call_hierarchy/plan.md`
  - 记录 P8 目标、范围、风险档、诚实性策略、计划与 DoD。
- `codegraph/api.py`
  - 新增 module-level 与 `CodeGraph` 的 `find_callers` / `find_callees`。
  - 新增 call-edge stability/cross-TU helper、scope/health 降级、background-index non-exhaustive guard。
- `codegraph/engines/clangd_adapter.py`
  - callHierarchy observation 补 `total_results`，与 references 分页语义对齐。
- `tests/test_api.py` / `tests/test_clangd_adapter.py`
  - 覆盖 callers/callees API、unsupported、empty unresolved、scope honesty、short plateau、direction/relation、non-exhaustive guard、adapter total_results。

## 进度日志
- 2026-07-08：从 `main@3bad237` 创建分支 `phase/8-call-hierarchy`。
- 2026-07-08：baseline 测试通过：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`，150 passed in 7.06s。
- 2026-07-08：真机环境确认：`clangd --version` 为 Ubuntu clangd 18.1.3；rw_arm 现有 background-index 为 3593 `.idx` / 47M。
- 2026-07-08：P3 adapter 探测显示 `textDocument/prepareCallHierarchy` 能定位函数 root；原始 LSP 探测确认 `callHierarchy/incomingCalls` 可用，`callHierarchy/outgoingCalls` 返回 `method not found`。
- 2026-07-08：跨 TU incoming 探测：`gst_element_set_state` 返回 3 条 incoming edges，caller files 包含 `gstutils.c` 与 `gstelement.c`；`gst_object_unref` 返回 66 条 incoming edges，caller files 包含 `gstelement.c` / `gstutils.c` / `gstobject.c`。
- 2026-07-09：复查 outgoing 是否姿势问题：initialize 返回 `server_callHierarchyProvider=true`；同一个 `prepareCallHierarchy` item 原样传给 `incomingCalls` 成功、传给 `outgoingCalls` 仍返回 `-32601 method not found`。扩大 client capabilities 后结果相同。结合 LLVM 20.1 release notes（clangd 20 新增 outgoing calls）与 llvm-project PR #117673（2024-12 合入 outgoingCalls 绑定），判定 clangd 18.1.3 真不支持 `callHierarchy/outgoingCalls`，不是客户端姿势问题。
- 2026-07-09：实现 P8 API。`find_callers` 使用 query kind `relation`，语义边 relation=`must`，降级候选 relation=`may`；`CallEdgeResult` 方向保持 design 契约。`find_callees` 走同一 API 形态，当前 clangd 18.1.3 outgoing 缺失时结构化 FAILED。
- 2026-07-09：真机验证发现 `gst_object_unref` incoming callers 在 background-index 加载中存在短平台期；将 call-edge ready 改为 3 次连续同签名稳定，并补单测防回退。
- 2026-07-09：测试与静态 gate：全套 pytest 158 passed；ruff passed；black --check passed；mypy codegraph passed。完整 `mypy codegraph tests` 仍会命中既有测试 typing debt（如 tests 中 `Credibility(**dict[str, object])`、union narrowing），本阶段不扩大修。
- 2026-07-09：真机 API 验收：`gst_element_set_state` callers 返回 OK/complete/indexed_project/total=387，semantic=379，candidates=8，exhaustive=False；`gst_object_unref` callers 返回 OK/complete/indexed_project/total=2951，limit=1000 页内 semantic=900/candidates=100，exhaustive=False；`find_callees(gst_element_set_state)` 返回 FAILED + CALLHIERARCHY_UNSUPPORTED；索引快照前后 unchanged。
- 2026-07-09：自查 `gst_element_set_state` 的 387 vs 早期探测 3：裸 adapter 单层 `callHierarchy/incomingCalls` 连续轮询显示 `1 -> 3 -> 387 -> 387...`，未做递归/传递展开；差异来自 background-index 加载不足。387 是 clangd 一层 direct incoming callers 稳定结果。自查 empty：prepare 定位不到与 located-but-empty 在当前 observation 形状下均表现为空 call_edges，API 返回 `UNRESOLVED/unknown/negative_scope=none/exhaustive=False`，不产 not_found。
