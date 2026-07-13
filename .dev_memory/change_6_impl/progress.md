# Change 6 Implementation - Multiversion clangd / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 版本戳只在完整建库成功、分片稳定、health 判定完成后写入；查询路径只读。
  - 原因：中途失败或未稳定的索引不能获得版本认证。
- 版本戳采用规范化完整版本（含 patch，如 `clangd 21.1.1`）精确匹配。
  - 原因：change_6 以保守隔离优先，暂不假设同 major/minor 的索引兼容。
- 存量 cache 无 stamp 视为 `index_engine_unverified`：health 降为 unknown，复用 `INDEX_UNKNOWN` 并写明 detail；不新增冻结设计之外的 IssueCode。
  - 迁移：优先空目录重建；已确认来源的存量索引仅允许显式 `--stamp-existing-index` 补 stamp。
- 已有分片且无 stamp 时，普通 build-index 不自动认领；已有 stamp 与当前 clangd 不符时，建库前拒绝启动。
  - 原因：clangd background-index 会复用并改写现有分片，增量启动后补 stamp 会把未知/异版本 cache 错误认证为当前版本。
- API 内部索引状态携带 health、reason、期望版本与 stamp 版本；路由仍只接收既有 `IndexHealth`，API 在结果上补结构化 mismatch/unverified note。
  - 原因：不扩大 P2 路由契约，同时保证结构化原因不在枚举降级时丢失。

## 改动摘要
- `codegraph/engine_version.py`：stdlib-only clangd 版本规范化、LSP initialize 提取与二进制探测。
- `codegraph/types.py`：纯附加 `IssueCode.INDEX_ENGINE_MISMATCH` 与 `QueryResult.engine_version`。
- `codegraph/engines/clangd_adapter.py`：记录当前 clangd 版本；callHierarchy unsupported 收紧为明确 method-not-found / JSON-RPC `-32601`。
- `codegraph/indexing.py` / `tools/build_index.py`：`.codegraph_engine` 三态、建库成功后写 stamp、建库前污染守卫、显式 `--stamp-existing-index`。
- `codegraph/api.py`：BuildConfig 版本隔离守卫、预启动 mismatch 拦截、health/scope 诚实降级、仅 call graph 传播 `engine_version`。
- 测试：stamp 三态、patch 精确匹配、显式迁移、拒绝自动认领、预启动拦截、版本元数据、unsupported 收紧及 P1-P8 回归。

## 进度日志
- 2026-07-13：开 stage 准备；从 `main@7cd0bd1` 创建 `impl/change-6-multiversion`，baseline `159 passed in 3.74s`。
- 2026-07-13：确认 stamp 三态语义并开始实现；补充建库前防“无 stamp 增量洗白”的守卫决策。
- 2026-07-13：实现中发现 LSP initialize 后才查 mismatch 已太晚，clangd 可能先改写 cache；默认真实 adapter 改为先执行 `clangd --version` + stamp 比对，已知 mismatch 时不启动 clangd，直接结构化降级。
- 2026-07-13：自审发现预启动 guard 一度把 explicit function kind 降为 UNKNOWN；修为只降 health/scope，保留真实 symbol_kind 与 active_config。
- 2026-07-13：最终 deterministic gate：全套最终复跑 `168 passed in 3.16s`；ruff、black --check、带固定 tree-sitter binding 的 mypy codegraph、compileall、git diff --check 全绿。coverage：总计 95%，api 95%，indexing 91%，clangd_adapter 99%，engine_version 92%。
- 2026-07-13：存量三套真实 cache 首次 inspect 均无 stamp：18/21/22 分片 3593/3595/3596，均返回 UNKNOWN + `index_engine_unverified`；用各自 clangd 显式 `--stamp-existing-index` 后恢复 COMPLETE，分片数不变。
- 2026-07-13：三版本真机：18 refs 389/62、callers 387/62、callees FAILED；21/22 refs 389/62、callers 386/61、callees OK 3 edges。call graph engine_version 分别正确，其他查询为 None；所有 positive `is_exhaustive=False`，不存在符号均 UNRESOLVED/UNKNOWN。
- 2026-07-13：故意用 clangd 21 配 18 cache：0.097s 返回 UNRESOLVED/UNKNOWN + `INDEX_ENGINE_MISMATCH`（18.1.3 vs 21.1.1）；idx 数量/字节/max mtime 前后相同，确认进程启动前拦截、无污染。
- 2026-07-13：完成 Codex 自审 + gstack Claude 独立审查。Claude 分模块提出 5 条候选 finding，逐条核验后均不成立：`Note` 非 frozen；非 call graph 的 `engine_version=None` 是冻结契约；生产版本探测均走同一 normalize；无 stamp partial cache 必须拒绝自动认领；inspect 比对必须知道当前 clangd。无有效 BLOCKER/MAJOR。
- 2026-07-13：Kimi CLI 路因会员权益校验 402 失败，未计入 review 通过数；未将能力失败伪装成审查结果。
