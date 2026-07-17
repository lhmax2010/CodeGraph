# Change 6 Implementation - Multiversion clangd / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 第五轮将单一 `.codegraph_engine` 拆为 dirty/committed 双标记，并增加 cache 级共享/独占锁。
  - 原因：单 stamp 无法同时表达“版本所有权已认领”和“完整建库已认证”；认领前置后，保留 stamp
    会让 SIGKILL 的 partial shards 假 complete，回滚 stamp 又会留下有分片无 owner 的锁死状态。
  - 状态机：`.codegraph_building` 存在时恒不 complete；同版本在独占锁下可接管，异版本 mismatch；
    dirty 与 committed 版本不一致不选择任一方，按 `index_engine_version_inconsistent` fail-closed。
    成功顺序为发布 committed、fsync、删除 dirty、再次 fsync；中间崩溃仍由 dirty 优先。
- `run_background_index()` 定义为完整建库入口：发布/接管 dirty 后清除全部旧 `.idx`，每次从零。
  - 原因：同版本接管旧 partial shards 时，旧分片数可能立即满足稳定判据并假 complete；分片可再生，
    保守重建优于复用无法证明完整的残留。增量建库不在该入口承诺内。
- cache 并发统一由 `.cache/clangd/.codegraph_index.lock` 协调：builder/追认持独占锁，API 从所有权
  校验前到 engine 关闭持共享锁。
  - 原因：marker 原子发布只能保护 owner 文本，不能保护声明所有权前后的分片副作用；共享/独占锁
    把 API、builder、CLI 的 check-to-use 窗口纳入同一协议。
  - 无 stamp 的 API 查询仍允许保守使用，但实际 adapter 强制 `background_index=false`；health/scope
    降级之外再加行为防线，不向未确认所有权的 cache 写入。
- LSP 初始化拆为 initialize request 与 initialized notification：实际 serverInfo 版本复核、dirty
  发布和旧分片清理完成后才发送 initialized，随后才打开 TU。
  - 原因：正确性不再依赖 clangd 当前版本“didOpen 前碰巧不写 shard”的实现细节。
- 第四轮“用 committed stamp 认领、失败回滚”的单标记方案已被第五轮 dirty/committed 双标记替代。
  - 原因：单标记保留会让 SIGKILL 后的 partial shards 假 COMPLETE，回滚又会留下有分片无 owner 的死态；
    第五轮改为 dirty 持续表达未完成所有权，只有 COMPLETE 才发布 committed 认证。
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
- 第六轮锁协议固定为 `cache lock → committed lease → dirty lease`，释放严格逆序；cache lock 永不由
  CodeGraph 删除，flock 后复核路径与 fd inode，marker lease 直接锁住已发布 inode。
  - 原因：cache lock 路径被外部删除重建时，仅靠 cache flock 会形成 split-brain；committed/dirty
    lease 分别把活跃 API 和 builder 与真实 marker inode 绑定，关闭 builder×builder 与 API×builder
    两类交错窗口。
- index/control 目录与 marker 发布均采用 `lstat`、`O_NOFOLLOW`、fd/path inode 复核；managed
  `index` symlink、control-dir symlink 和 marker symlink 一律 fail-closed。
- CodeGraph API 创建的 adapter 一律 `defer_initialized=True`；initialize request 只读取 serverInfo，
  ownership/版本/committed lease 复核后才发送 `initialized`。P3 默认仍为 `False`，保持既有适配器行为。
- 断电语义选择“明确边界”而非逐 shard fsync：真实 1303-TU/13.38MB 分片复制后逐文件+目录 fsync
  实测约 31.2s；MVP 保证正常并发与进程崩溃/SIGKILL 恢复，不承诺机器断电原子性。
- verified 同版本 API 继续允许 clangd 刷新 cache；clangd 21/22 的 `BackgroundIndexStorage::storeShard`
  使用 `llvm::writeToOutput` 临时文件后原子替换。CodeGraph lease 只阻断 builder/跨版本交错。

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
- 2026-07-15：第五轮将所有权与成功认证拆为 `.codegraph_building` / `.codegraph_engine`，并以
  `.cache/clangd/.codegraph_index.lock` 统一 builder/追认的独占锁和 API 的共享锁。dirty 存在时
  health 恒非 COMPLETE；同版本在独占锁下清除旧 `.idx` 后从零接管，异版本 mismatch，dirty 与
  committed 版本不一致按 `index_engine_version_inconsistent` fail-closed。
- 2026-07-15：builder 时序固定为 exclusive lock → initialize request → serverInfo 实际版本复核 →
  发布 dirty → 清旧 shards → `initialized` → `didOpen`。dirty 发布或清理失败均不发 `initialized`，
  从协议时序上阻止 clangd 在所有权确认前开始后台工作。
- 2026-07-15：真实 SIGKILL 验证：100-TU ARM 子集在 207 shards 时 kill，留下 dirty 且无 committed，
  即使 `207 >= 100` 仍为 UNKNOWN/build_in_progress；同版本直接接管、清旧并重建到 427 shards，
  8.599s 后才发布 committed 并恢复 COMPLETE。1303-TU 全量重试在 809/1303 的中间 plateau 被保守判
  INCOMPLETE、dirty 保留，未将部分索引认证为 complete。
- 2026-07-15：真实优雅失败验证：50-TU ARM 子集首次 `max_wait=0` 在 357 shards 返回
  UNKNOWN/index_build_not_stable，dirty 保留；不删除目录直接同版本重试，7.861s 建到 446 shards，
  commit 后 dirty 清除并恢复 COMPLETE。
- 2026-07-15：真实并发验证：21 vs 22、21 vs 21 各 5 轮 barrier 竞争，均只有一个 LSP 建库启动；
  输家在任何 TU/shard 副作用前返回 `index_engine_build_in_progress`，最终 committed 与 shards 单一版本。
  API×builder 真实交错中，API 持共享锁时 builder 0.005s 被挡，阻断期间 shard 快照不变，API 查询
  保守返回 UNRESOLVED/unknown。
- 2026-07-15：未认证 cache 的 API 行为防线已验证：adapter 强制 `background_index=false`，查询前后
  cache 快照不变；canonical 损坏文本、symlink、marker 不一致及守卫扫描失败均 blocking。三版本回归
  保持 refs 389/62、18 callees FAILED、21/22 callees OK 3；21 错配 18 cache 0.152s 拦截且零污染。
- 2026-07-15：开发机 Snap 更新移除了旧 `.venv` 所指 Python 3.11，原环境成为断链；保留旧目录备份，
  用系统 Python 3.12 无损重建 `.venv` 并恢复固定 tree-sitter/gate 版本。最终 gate：249 passed，
  coverage 总计 92%、`api.py` 92%、核心 `indexing.py` 90%；ruff/black/mypy/compileall/diff-check 全绿。
  7 条核心并发/崩溃测试连续 30 轮全部通过。
- 2026-07-15：第五轮 gstack Claude 对完整 delta 做 tool-less 独立 review，240s 内未返回 JSON/文本，
  按能力超时记录，不计 APPROVE；分支仍须用户侧异构多路全票确认，未自行放行。
- 2026-07-15：第六轮开始实现保护机制自身的 namespace 绑定：managed index symlink 在 clangd 启动
  前拒绝；cache lock 永不删除且 flock 后复核 inode；builder/API 分别持 dirty EX / committed SH
  lease，锁路径被外部替换时仍不能越过真实 marker inode。
- 2026-07-15：adapter 增加默认关闭的 `defer_initialized`，CodeGraph 统一显式开启；P3 默认行为不变，
  API 在所有守卫通过后才通知 initialized。首轮聚焦回归为 169 passed，继续补全第六轮并发真机 gate。
- 2026-07-15：崩溃恢复后逐文件核对第六轮未提交工作区，无冲突标记或半写文件。完成 namespace
  绑定加固：managed index/control 目录拒绝 symlink，cache lock 永不由 CodeGraph 删除且 flock 后
  复核 inode；builder 持 dirty EX lease，verified API 持 committed SH lease；显式追认和直接 stamp
  也先发布/获取 marker lease，lock 路径被替换后仍不能绕过活跃 owner。
- 2026-07-15：自审补齐 attestation 的 TOCTOU 回归：活跃 dirty + lock 路径替换时 direct-write 与
  `--stamp-existing-index` 均被挡；committed/dirty 在复核窗口出现时 fail-closed；回滚只按 inode 删除
  自己创建的 dirty，路径被替换时不误删；commit I/O 失败结构化为
  `index_engine_stamp_write_failed`。
- 2026-07-15：第六轮 deterministic gate：全套 coverage 命令 `271 passed in 18.39s`，总覆盖率
  92%，`api.py` 92%、核心 `indexing.py` 90%、adapter 99%；ruff、black --check、mypy、compileall、
  `git diff --check` 全绿。10 条 lock/lease/symlink/initialized 核心测试连续 30 轮全部通过。
- 2026-07-15：第六轮真实防线 spot-check：真实 clangd 的 managed index symlink 在启动前阻断且
  外部目录快照不变；删除 lock pathname 后，builder×builder 与 API×builder 均由 dirty/committed
  lease 返回 build-in-progress；21 对 18 cache mismatch 在约 0.108s 拦截且快照不变；三版本
  callees 保持 18 FAILED、21/22 各 3 edges。
- 2026-07-15：`389/62` 当前复跑受宿主机资源阻塞，未计 gate 通过：无关 `ld.lld` 长时间占用约
  22% 内存，available RAM 约 4 GiB、4 GiB swap 已满。CodeGraph clangd 21 在 90s readiness
  配置下最终 120.183s 返回 UNRESOLVED/unknown、18 candidates，分片快照 3595/40114730 bytes/
  max-mtime 前后完全不变。使用旧 adapter 默认 initialized 时序的直接 P3 探测同样只能得到局部
  结果，说明当前失败是环境资源压力而非本轮 defer 时序回归；按同一问题三次失败上限停止重试，
  暂不宣称第六轮完成、暂不送异构 review。
- 2026-07-17：宿主机 available RAM 恢复至约 22 GiB 后继续真机 gate。先排除一次错误探针：版本
  专用 CDB 的 canonical URI 位于 GBS build root，源码镜像 URI 只能得到诚实的单 TU 结果，不能用于
  `389/62` 验收。使用归档 spot-check 的 exact build-root URI `gstelement.c` zero-based `[2950,0]`
  后，P3 adapter 日志确认加载 CDB、enqueue 1303 commands，并从磁盘加载 background index。
- 2026-07-17：正式 CodeGraph API 在 clangd 21 cache 上连续三次复现 `389 refs/62 files`：每次均
  `OK/complete/indexed_project`、`381 semantic + 8 candidates`、`is_exhaustive=False`，耗时
  `2.930s / 2.953s / 2.925s`。分片快照 `(3595, 40114730 bytes, max-mtime)` 前后完全不变；
  第六轮 `389/62` 真机阻塞关闭，进入最终提交与用户异构多路 Review 准备。
