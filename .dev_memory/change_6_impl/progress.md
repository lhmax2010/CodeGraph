# Change 6 Implementation - Multiversion clangd / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 版本戳在 LSP 实际版本复核后、首个 TU 打开前原子认领并持锁；仅完整建库成功、分片稳定且 health COMPLETE 时保留，正常失败只回滚本 builder 创建且 inode 未变的 stamp。
  - 原因：所有权必须先于 clangd 分片副作用；同时中途失败或未稳定的索引不能长期获得版本认证。
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
- `codegraph/indexing.py` / `tools/build_index.py`：`.codegraph_engine` 三态、建库前原子认领与同版本互斥、失败 inode 回滚、建库前污染守卫、显式 `--stamp-existing-index`。
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
- 2026-07-14：第三轮守卫加固采用两层物理约束：`index_engine_stamp_invalid` 复用 `INDEX_UNKNOWN` 但列为 blocking；`write_index_engine_version()` 只允许缺失 stamp 的排他首建或同版本幂等，冲突/损坏均拒绝。builder 在 LSP initialize 得到 serverInfo 实际版本后、任何 TU 打开前再次检查所有权；API 缺 stamp 仍保守可用，非空未验证 cache 的 builder 仍不自动认领。
- 2026-07-14：stamp 首建采用“完整临时文件 + `link()` 排他发布”，既不暴露半写内容，也不以 replace 覆盖并发 owner；若目标已出现，只接受同版本幂等，冲突/损坏均 fail-closed。自审补掉 stamp 为目录且零 `.idx` 时的 preflight 早退，并让 LSP serverInfo 与 `--version` 不一致在无 stamp 新库上也于首个 TU 前停止。
- 2026-07-14：第三轮 deterministic gate：187 passed；coverage 总计 92%（api 92%、indexing 89% 综合，二者行覆盖均超过 90%）；ruff、black --check、mypy、compileall、git diff --check 全绿。新增 wrapper、create-only/幂等/冲突/并发、非法内容/目录/PermissionError、CLI structured block 与 unverified 回归。
- 2026-07-14：真机 wrapper（`--version` 伪装 99.99.99、实际 exec 系统 clangd）在有 stamp/无 stamp 两种路径均于 `open_file` 前拦截，stamp 未变/未创建。版本专用 cache：21/22 references 389/62、callees 3；18 高负载首轮诚实降级 2/unknown，热态复跑恢复 389/62、callees unsupported；三套分片快照均不变。21 对 18 cache 在 0.085s 内 mismatch 拦截且快照不变。
- 2026-07-14：第三轮异构复核：Codex 按“路径 × stamp 状态 × 版本状态”自审无遗留 BLOCKER/MAJOR；gstack Claude 完整 diff 首次 180s 超时未计票，拆成生产守卫聚焦审查后明确 `VERDICT: APPROVE`。Kimi CLI 复探 180s 无输出超时，未计票；不以能力失败补票。
- 2026-07-14：第四轮并发加固改为“认领先于副作用”：LSP serverInfo 与 `--version` 通过后，builder 在任何 `open_file` 前用完整临时文件 + `link()` 原子发布 stamp；临时 inode 先持 `flock`，发布后删除临时文件名但锁随 fd/inode 保持。跨版本竞争由 stamp 版本拒绝，同版本竞争由 stamp 自身的非阻塞排他锁返回 `index_engine_build_in_progress`，不增加锁文件。
- 2026-07-14：正常建库失败仅在“本 builder 创建 + 路径仍指向同 dev/inode”时回滚 stamp；硬崩自动释放 flock 但留下保守认领，同版本可后续重建、异版本继续被挡。`index_engine_build_in_progress` 与 `index_engine_stamp_write_failed` 均为 reason，API 复用 `INDEX_UNKNOWN` 并提供结构化 detail，未新增冻结 IssueCode。
- 2026-07-14：stamp 读写统一采用 `lstat` + `O_NOFOLLOW` + `fstat` inode 复核，任何有效/悬空 symlink 均为 `index_engine_stamp_invalid`；索引目录扫描失败为 blocking `index_health_error`，API/builder/CLI 均不启动 engine。`--stamp-existing-index` 的 OSError 改为结构化 `index_engine_stamp_write_failed`，并在 CLI help/change_6 §6.1 明示其为操作者 provenance 断言，已污染的原始 3614 分片 cache 禁止追认。
- 2026-07-14：第四轮聚焦测试 `102 passed`；barrier 异版本/同版本/失败回滚与 fd 锁测试连续 10 轮全过（每轮 4 passed），ruff 聚焦检查全绿。完整 deterministic gate 与真机回归待执行。
- 2026-07-14：第四轮真实 clangd barrier：21.1.1 与 22.1.8 同时 initialize 后竞争同一临时 cache，仅 21 打开 TU 并产 1 shard，22 在副作用前 `index_engine_mismatch`；两个 21.1.1 同时竞争时仅一个打开 TU，另一个 `index_engine_build_in_progress`。两组最终 stamp/分片均只属于胜者。
- 2026-07-14：三版本真实回归：18/21/22 prewarm 分别 11.554s/6.328s/6.392s，references 均 389/62、OK/complete、`is_exhaustive=False`；18 callees FAILED + unsupported，21/22 callees OK + 3，engine_version 正确。查询耗时 refs 3.742s/3.623s/3.624s；三套 cache 的 idx 数量/字节/max mtime 前后完全不变。clangd 21 错配 18 cache 在 0.120s 内 UNRESOLVED + mismatch，快照不变。
- 2026-07-14：第四轮完整 deterministic UT 最终复跑 `217 passed in 4.30s`；ruff 与 mypy 全绿。coverage/black/compileall/diff-check 将在提交前最终复跑并以 result.md 为准。
- 2026-07-14：第四轮 gstack Claude 独立 review 两次均未形成投票：完整 delta 与仅 production-code 聚焦 delta 各在 180s 内无响应文本（第二次 response 为空），均按能力失败/超时处理，不计 APPROVE。分支推送后交用户侧其余异构路线复核，全票前不 merge。
- 2026-07-14：提交前最终 gate：`217 passed in 5.29s`，coverage 总计 92%、`api.py` 93%、核心 `indexing.py` 90%；ruff、black --check、mypy、compileall、git diff --check 全绿。
- 2026-07-14：针对“initialize 本身是否早于 claim 写分片”补真实 21/22 延时诊断：fresh CDB 上两进程完成 initialize 后强制停 2s，claim/open_file 尚未执行时两次观测均为 0 `.idx`；随后竞争仍仅胜者打开 TU并产 1 shard。当前 clangd 21/22 实证支持“首个 TU 打开是该建库流程的分片触发点”，未发现 pre-claim 副作用窗口。
