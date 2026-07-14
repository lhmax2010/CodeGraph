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
- 所有权检查优先于索引内容检查；只要目录已有有效 stamp，就先判匹配、mismatch 或 current engine unavailable，再检查 `.idx` 数量。
  - 原因：零分片或损坏内容不会消除目录所有权，其他版本仍不得启动并写入。
- 自定义 engine factory 通过独立 `engine_version_probe` 提供无启动版本声明；默认 probe 始终检查 `BuildConfig.clangd_path`。
  - 原因：测试桩不依赖宿主机 clangd，同时真实/自定义 factory 都不能绕过启动前所有权守卫；factory 实际版本在启动后、任何 warm/query 前再次复核。

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
- 2026-07-14：四路 review 裁决确认两个 MAJOR；清理 detached 工作区游离文档并恢复 `api.py` 后，在 `impl/change-6-multiversion@66b0cb8` 开始修复。
- 2026-07-14：实现所有权优先状态机与双层版本复核；无 stamp 保持 unverified 可用但 health/scope 降级，有 stamp 且当前版本不可探测则 factory 零调用 fail-closed。
- 2026-07-14：新增/翻转 4 条核心回归：冲突 stamp + 零 idx 仍 mismatch；非 idx 文件无 stamp 仍 unverified 且 build preflight 不认领；有 stamp + probe unavailable 时 factory 零调用；probe 声明与实际 engine 不一致时，启动后在任何 query 前复核为 UNRESOLVED。
- 2026-07-14：真机复核：clangd 21 对 18 cache 在 0.084s 内 mismatch 拦截且快照不变；真实 21 对临时“18 stamp + 零 idx”返回 mismatch，对无 stamp non-idx cache 返回 unverified。三版本最终均 refs 389/62；18 callees FAILED，21/22 callees OK 3 edges，三个 cache 快照均不变。
- 2026-07-14：当前机器一度 load average >11 且 swap 满，18 首次 prewarm 超时后只返回 2 refs/unknown（诚实降级）；热态复跑 prewarm 成功并恢复 389/62，未把降级结果冒充项目级完整结果。
- 2026-07-14：修复后 deterministic gate：172 passed；coverage 总计 92%（api 行 94%、indexing 行 91%）；ruff、black --check、mypy、compileall、git diff --check 全绿。等待修复后的异构多路 review。
- 2026-07-14：崩溃恢复后重新核验工作区与全部 deterministic gate，仍为 172 passed 且静态 gate 全绿。gstack Claude 前两次完整复核分别无输出卡住/180s 超时，第三次按两个 MAJOR 聚焦最终函数、调用点、核心测试与真机证据，明确给出 `VERDICT: APPROVE`，无遗留 BLOCKER/MAJOR；失败尝试未计作通过。
