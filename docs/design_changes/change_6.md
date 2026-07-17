# change_6：多版本 clangd support

- 变更类型：R1 变更（能力扩展）
- 触发阶段：Phase 8 后（call hierarchy 收口，多版本工具链验证）
- 发现方式：P8 探测 clangd 18.1.3 不支持 outgoingCalls + GBS 生产用 clangd 21.1.1；
  编译 18/21/22 三版本做真机 spot-check
- 决策日期：2026-07-10
- design 版本：v1.4.5 → v1.5.0

---

## 1. 问题

P8（call hierarchy）暴露：宿主机 clangd 18.1.3 **不支持** callHierarchy/outgoingCalls
（LLVM 20.1 release notes 确认 clangd 20 才加，PR #117673 2024-12 合入），故 find_callees
在 18 上只能诚实 FAILED。但：

- **GBS 生产工具链用 clangd 21.1.1**（支持 outgoing）——CodeGraph 最终服务 GBS/Tizen 代码，
  开发/测试用 18 而生产用 21，是版本不一致。
- **发布后开发者环境版本必然不一**（有人 18、有人 21、有人 22.1.8——最新 release）。
- LLVM 还在持续升级。

绑死单一 clangd 版本（design v1.4.5 假设 clangd 18.1.3）不可持续。需要 CodeGraph
**support 多版本 clangd，运行时探测能力，诚实反映每个版本能给什么**。

---

## 2. 三版本真机验证（18.1.3 / 21.1.1 / 22.1.8）

编译 clangd 21.1.1、22.1.8 到 /home（只 build clangd target，独立 prefix），18.1.3 用系统版本。
每个 clangd 用**独立 CDB 目录 + 独立 .cache/clangd/index**（见 §4 索引隔离）。对 rw_arm
（gstreamer，1303 TU）做 spot-check：

| 属性 | 18.1.3 | 21.1.1 | 22.1.8 | 结论 |
|---|---|---|---|---|
| missing search（各 kind_filter） | UNRESOLVED | UNRESOLVED | UNRESOLVED | 一致·不产 not_found |
| explicit kind 元数据 | 保留真实 kind | 同 | 同 | 一致·降 health 不降 kind |
| bg=False 查现存符号 | UNRESOLVED | UNRESOLVED | UNRESOLVED | 一致·不虚假否定 |
| search(gst_buffer_ref) | OK/gstbuffer.c/total 2 | 同 | 同 | 一致 |
| **find_references(gst_element_set_state)** | **389/62** | **389/62** | **389/62** | **一致** |
| is_exhaustive | 恒 False | 恒 False | 恒 False | 一致 |
| empty refs | UNRESOLVED | UNRESOLVED | UNRESOLVED | 一致 |
| **find_callers(gst_element_set_state)** | **387** | **386** | **386** | **版本相关** |
| **find_callees(gst_element_set_state)** | **FAILED** | **OK/3 edges** | **OK/3 edges** | **版本相关** |

### 2.1 关键差异分析
- **find_callers 387(18) vs 386(21/22)**：18 多 1 条 edge。经 raw LSP `incomingCalls` 字段核实
  （非推测）：
  - 18-only edge 原始字段：`from.name=gst_adaptive_demux_stop_tasks`、
    `from.uri=file:///.../subprojects/gst-plugins-good/ext/adaptivedemux2/gstadaptivedemux.c`、
    `from.selectionRange=line 3012(0-based)`、`fromRange(call-site)=line 2366(0-based) char 8`。
  - 换算 1-based：文件 `gst-plugins-good/ext/adaptivedemux2/gstadaptivedemux.c`，
    from_symbol `gst_adaptive_demux_stop_tasks @ 3013`，call_site `2367:8`。
  - 该源码行是 `GstClockTimeDiff ts;`（**变量声明，非调用**）；该文件内
    `grep -c gst_element_set_state`（**裸 token**；注意 GStreamer 用 GNU 风格 `name (args)`，
    带括号的 pattern `gst_element_set_state(` 会漏匹配真实调用，复核时勿用）**0 命中**，
    stop_tasks 函数体不调用 gst_element_set_state。
    （真正的判别依据是 edge 的 **from.uri 指向 good 文件**，不是 grep 命中数。）
  - **注意**：存在另一同名文件 `gst-plugins-bad/gst-libs/gst/adaptivedemux/gstadaptivedemux.c`，
    其 2367 确是真实 `gst_element_set_state(src, GST_STATE_READY)` 调用；但 **18 的 edge URI
    指向的是 good 文件、不是 bad 文件**，故不是"指向真实调用"，而是把 good 文件一行变量声明
    误归属。**18 是 false positive；21/22 去掉它是更准，不是漏报真实调用。** 22 与 21 一致佐证。
  （核实方法可复现：看 18 结果的 raw incomingCalls URI + selectionRange，按完整路径查源码行。）
- **find_callees FAILED(18) vs OK(21/22)**：outgoingCalls 需 clangd 20+。21/22 点亮，返回 3 条
  direct callee（g_return_if_fail_warning / g_type_check_instance_is_a / gst_element_get_type）。
  同一份代码（P8 接标准 LSP outgoingCalls）在支持版本自动可用。

### 2.2 核心结论
1. **CodeGraph 诚实性属性【版本无关】**：not_found、is_exhaustive、find_references(389/62)、
   降 health 不降 kind、bg=False 安全——三版本完全一致。change_5/P7 建立的诚实性不是
   clangd 18 特有，是跨版本稳健的。
2. **call graph 结果【版本相关】**：find_callers 数量、callHierarchy 支持性随版本变
   （且新版本更准/更全）。
3. **索引【跨版本非只读】**：clangd 会改写 cache（18 建 3593、21 独立建 3595、22 独立建 3596；
   原 rw_arm cache 被 21 接触后写到 3614）。

---

## 3. 决策

**CodeGraph support 多版本 clangd（18.1.3 / 21.1.1 / 22.1.8+），运行时探测版本与能力，
诚实反映每个版本能给什么。** 落地为三个机制：

### 3.1 能力探测 + 诚实降级（层次 A）
callHierarchy 逐方向 runtime probe（incoming / outgoing 分开）。outgoingCalls 需 clangd 20+；
不支持的方向 → FAILED + CALLHIERARCHY_UNSUPPORTED，**不用 references+AST 伪造调用图**。
实现接标准 LSP，支持的版本自动点亮（find_callees 18 FAILED / 21/22 可用，同一份代码）。
这已由 P8 形态 A 实现 + `test_find_callees_routes_outgoing_edges_when_engine_supports_them`
预验证，真机 clangd 21/22 兑现。

### 3.2 索引按 clangd 版本隔离（硬约束）
每个 clangd 版本【必须】用独立 CDB 目录 + 独立 .cache/clangd/index，不跨版本共享——因为
clangd 跨版本会改写索引（实测污染）。CodeGraph 的 BuildConfig.compile_commands_dir 直接切
版本目录即可。

### 3.3 clangd 版本作为可追溯元数据（不入可信度判断）
call graph 类结果携带产生它的 clangd 版本（如"此结果由 clangd 21.1.1 产生"），让消费方
可追溯"这个 386/387 依赖 clangd 版本"。
**关键设计判断**：诚实性属性版本无关（三版本一致），故【不】把 clangd 版本塞进每个
credibility 的可信度判断（那会让版本无关的属性也背上版本负担）；仅作为结果的**可追溯元数据**。
这是层次 A+ 而非完整层次 B——因为 spot-check 证明"版本差异只在 call graph 数量、且新版本
更准"，不是"多个版本各说各话无对错"，所以记录版本用于追溯/解释足矣，不需版本参与可信度评分。

---

## 4. 为什么不做更重的方案

- **不做"版本进每个 credibility 的可信度判断"**：诚实性属性三版本一致（数据证明），给它们
  标版本是无谓负担。call graph 数量差异是"旧版本 bug、新版本修"性质（386/387 那条是 18
  false positive），不是"版本分歧无对错"，故记录版本可追溯即可，不需版本参与评分。
- **不做"锁定单一版本 + 要求所有人用同一 clangd"**：违背发布现实（开发者环境不一），且
  放弃了新版本的更准结果（callees 点亮、callers 去掉 false positive）。
- **不做"references+AST 兜底 callees"**：契约禁止 + 硬凑的调用图不诚实（clangd 不给就诚实说
  不支持，等版本升级）。

---

## 5. design 改动清单（v1.5.0）

1. **§1.4 clangd 假设**：单版本 18.1.3 → 多版本 support（18/21/22，运行时探测）+ 三条关键
   事实（诚实性版本无关、call graph 版本相关、索引按版本隔离）。
2. **§4.1.1 find_callers/callees 契约**：callHierarchy 逐方向 runtime probe；outgoing 需 20+；
   不支持方向 FAILED；结果携带版本元数据。
3. **§4.1.2 QueryResult 结构**：新增 `engine_version: str | None = None`（可追溯元数据，
   纯附加、默认 None、不进 Credibility、不参与 check_invariants/QR/INV；call graph 结果由
   adapter 填，其他留 None）。
4. **C-2 修订**：索引的 clangd 版本隔离改为 CodeGraph 配置层【强约束】（原"消费方自管"与
   change_6 冲突）；代码 staleness 仍消费方自管。
5. **§6 R-技6**：从"callHierarchy 在 clangd 18 支持差异"泛化为"clangd 跨版本能力/结果差异"，
   缓解=能力探测 + 版本隔离 + 版本元数据 + 三版本 spot-check 已验证诚实性一致。
6. **§6 Top3 R-技6 条**：同步为泛化后表述（P8 已交付、三版本已验证）。
7. **§10 P8 DoD**：callHierarchy 单版本验证 → 多版本能力验证（逐方向 probe、outgoing 需 20+）。
8. **§1.4 clang-tools-18 [OPEN]**：→ 与选定 clangd 版本匹配的 clang-tools/clangd-indexer
   （多版本后须同版本保索引兼容）。
9. **§0 版本号 + changelog**：v1.4.5 → v1.5.0。

---

## 6. 后续实现（change_6 落地）

change_6 是 design 变更；对应代码实现（多版本能力判定、版本元数据入结果、索引版本隔离的
BuildConfig 支持）在 change_6 review 通过后进行。P8 的 callees capability 处理（method not
found → FAILED）已是第一个实例；需补：clangd 版本探测 + 结果携带版本元数据（engine_version）
+ BuildConfig 索引版本隔离的规范化。

### 6.1 实现期待补的防线（review 指出，登记）
- **[缺防线] 索引版本隔离是"强约束"但【无运行时守卫】**：若操作方违反（两个 clangd 版本
  共享同一 cache），index_health 判据（shards ≥ unique_TU）仍会报 complete，CodeGraph
  不给任何信号——这对"绝不静默误导"的立身之本是个缺口。
  建议实现：cache 目录落一个引擎版本戳（如 `.codegraph_engine` 记 clangd 版本），CodeGraph
  打开索引时比对当前 clangd 版本；不匹配 → 新 IssueCode `INDEX_ENGINE_MISMATCH` +
  index_health 降级（不静默使用可能被别版本改写的索引）。
  优先级：实现期（change_6 代码落地时）或二期；design 层已把隔离定为强约束，此为执行侧防线。
- **存量索引追认是操作者断言，不是自动检测**：`--stamp-existing-index` 只能在操作者已经从
  外部证据确认建库版本时使用。无 stamp 的 cache 无法从分片内容反推出历史 builder；若追认成
  错误版本，会把一份错版索引伪装成可验证的健康索引。来源不确定时必须在空目录中用目标 clangd
  重建。真机原始 `rw_arm` cache 曾被 clangd 21 接触并从 3593 增至 3614 分片，已发生跨版本
  污染，禁止对该目录执行追认。
- **实现采用 dirty/committed 双标记**：`.codegraph_building` 只表示某一精确 clangd 版本已
  认领一次尚未认证完成的完整建库；`.codegraph_engine` 只在分片稳定且 health=complete 后发布。
  只要 dirty 存在，任何 shard 数都不得解释为 complete；同版本可在取得 cache 独占锁后清除旧
  `.idx` 并从零接管重建，异版本必须 fail-closed。committed 已发布但 dirty 尚未清除时仍以 dirty
  为准，避免提交窗口崩溃把半完成目录伪装成健康索引。
- **cache 读写共用锁协议**：完整 builder 与 `--stamp-existing-index` 持独占锁；启用
  background-index 的查询从所有权校验前到 clangd 关闭持共享锁。锁竞争或锁自身不可验证均按
  `INDEX_UNKNOWN` 阻断，防止 API 与 builder 或两个异版本 builder 交错写同一 cache。无 stamp
  存量 cache 仍可保守查询，但 adapter 强制 `background_index=false`，不向未确认所有权的目录
  写分片。
- **锁与 marker 的 inode 绑定协议**：cache lock 文件是永久基础设施，CodeGraph 不删除它；取得
  `flock` 后必须复核 fd 与路径仍指向同一 inode。锁序固定为 cache lock → committed marker lease →
  dirty marker lease，逆序释放。builder 持 dirty 独占 lease 覆盖认领至 commit/失败全程，API 对
  verified cache 持 committed 共享 lease 覆盖 adapter 生命周期；即使 lock 路径被外部删除重建，
  活跃 builder/API 仍不能与新进程形成 split-brain。index/control 目录及 marker 必须是本目录内
  的真实目录/普通文件，任何 symlink 或身份替换均 fail-closed。
- **完整建库入口不提供增量语义**：`run_background_index()` 每次在发布 dirty 后清除既有 `.idx`
  并从零建库。这样同版本接管崩溃残留时不会被旧 partial shard 的稳定计数提前判 complete；增量
  索引如需支持，必须另设带独立完成证据的入口。
- **崩溃与断电边界**：上述协议保证正常并发、优雅失败及进程崩溃/SIGKILL 后的保守恢复；不承诺
  机器断电时 shards 与 marker 的跨文件原子持久化。对真实 1303-TU 索引逐分片 fsync 的实测额外
  耗时约 31.2s，MVP 选择明确声明边界而不承担该成本。断电后应以 dirty/health 重新验证，无法
  证明完整时从零重建。
- **verified API 的同版本刷新语义**：多个已验证 API 查询可由同版本 clangd 刷新自身 cache；
  clangd 的 shard store 使用临时输出后原子替换。CodeGraph 的 lease 负责阻断 builder/跨版本交错，
  不把同版本查询强制改成只读。该保证不放宽版本隔离，也不把 background-index 结果声明为穷尽。

## 7. 已验证事实（存档）
- 三版本编译：clangd 21.1.1（build 52min）、22.1.8（build 58min）到 /home，18 用系统版本。
- 三版本独立 cache：rw_arm-clangd18(3593)/21(3595)/22(3596)，各自 health=complete。
- 完整 spot-check 日志：`.dev_memory/change_6_multiversion/spotcheck-20260710.txt`
  （归档进 repo 以便复核；含三版本逐属性对比汇总。386/387 的 raw edge 字段见本文 §2.1）。
