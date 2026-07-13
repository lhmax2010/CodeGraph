# Change 6 Implementation - Multiversion clangd / Plan

## 目标
落实已冻结的 `docs/design.md v1.5.0` / `docs/design_changes/change_6.md`：
- 支持多版本 clangd 的版本探测与 callHierarchy 逐方向反应式能力判定。
- 为 call graph 查询结果填充 `QueryResult.engine_version` 可追溯元数据。
- 将 clangd 版本隔离规范化进 BuildConfig / index health 路径。
- 增加 `INDEX_ENGINE_MISMATCH` 运行时守卫，避免共享/污染 cache 被静默判为 complete。

## Baseline
- 分支基线：`main` @ `7cd0bd1`
- baseline 命令：`PYTHONPATH=.:tools /home/linhao/Toolchain/development/CodeGraph/.venv/bin/python -m pytest tests/ -q`
- baseline 结果：`159 passed in 3.74s`

## 风险档
- 高风险。
- 原因：本次改动跨 `types.py` schema、clangd adapter、API facade、index health、CLI/build-index 和真机多版本验证；其中 `INDEX_ENGINE_MISMATCH` 与 `_looks_unsupported` 都是 CodeGraph 诚实性防线，误实现会造成静默误导或能力误判。
- Review 要求：实现后必须过用户异构多路 review；真机验证覆盖 clangd 18/21/22。

## 范围边界
做：
- 运行时探测 clangd 版本，优先使用 LSP `initialize` 返回的 `serverInfo.version`，必要时 fallback `clangd --version`。
- 收紧 callHierarchy unsupported 判定：只认 JSON-RPC `-32601` 或明确 `method not found`，不再把任意含 `unsupported` 的错误吞成 `CALLHIERARCHY_UNSUPPORTED`。
- `QueryResult` 新增 `engine_version: str | None = None`，字段顺序保持 `total_hits -> notes -> engine_version`；仅 call graph API 填当前 clangd 版本，其他查询保持 `None`。
- BuildConfig 增加显式 index/engine version 元数据路径，规范化每个 clangd 版本使用独立 `compile_commands_dir`/cache。
- index cache 写入/读取 `.codegraph_engine` 版本戳；当前 clangd 版本与戳不匹配时 health 降级为 `unknown` 并发 `INDEX_ENGINE_MISMATCH` note。
- 测试覆盖 schema、unsupported 收紧、版本填充、mismatch health 降级、CLI/build-index stamp、三版本真机 spot-check。

不做：
- 不改 design 文档语义（v1.5.0 已冻结）。
- 不提前实现二期 clangd-indexer / 逐 TU 台账 / staleness 精确判定。
- 不改变 P6/P7/P8 的诚实性策略：background-index 仍不产 not_found，references/call graph 仍不声明 exhaustive。
- 不用 references+AST 伪造 callees；不支持方向继续 FAILED + `CALLHIERARCHY_UNSUPPORTED`。

## 计划步骤
1. Schema 与 IssueCode：
   - `QueryResult.engine_version` 加字段，保持字段顺序。
   - `IssueCode.INDEX_ENGINE_MISMATCH` 加入枚举。
   - 更新 routing/query result 构造路径以保持默认 `None` 不破坏旧查询。
2. clangd adapter：
   - 捕获 `initialize` result 的 `serverInfo.version`，标准化为如 `clangd 21.1.1`。
   - 暴露只读 `engine_version` 属性；fake client 测试覆盖有/无 serverInfo。
   - 收紧 `_looks_unsupported`，新增 method-not-found 与普通 unsupported 文本的分流测试。
3. API call graph 元数据：
   - `_find_call_edges` 在 call graph 成功/失败路径上使用 adapter 版本。
   - call graph `QueryResult.engine_version` 填版本；search/definition/references 保持 `None`。
4. 索引版本隔离与 mismatch 守卫：
   - 在 indexing 层提供 engine stamp 读写函数，`run_background_index` 成功时写当前 clangd 版本戳。
   - BuildConfig 读取 index health 时比对当前 clangd 版本与 cache stamp。
   - mismatch 时 health 降为 `unknown`，notes 加 `INDEX_ENGINE_MISMATCH`，不能静默 complete。
   - CLI `build_index.py` 将 clangd 版本/engine stamp 纳入 JSON 输出或 health report。
5. 测试：
   - 单测：schema 字段顺序/默认值、engine_version 只出现在 call graph、unsupported 收紧、mismatch 降级、stamp 写入。
   - 回归：P6/P7/P8 现有安全测试不破。
   - 真机：clangd 18/21/22 独立 cache 验证 callees 差异、engine_version、mismatch、refs 389/62、not_found/is_exhaustive 诚实性。
6. Gate：
   - `.venv` pytest 全套。
   - ruff / black --check / mypy。
   - 记录 progress/result 与真机数据。

## 依赖前置阶段
- 已 Merge：P1-P8。
- 已冻结设计：`docs/design.md v1.5.0`，`docs/design_changes/change_6.md`。
- 真机工具链：`/home/linhao/clang-toolchains/` 下 clangd 18/21/22 与版本专用 rw_arm cache。
