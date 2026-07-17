# Change 6 Implementation - Multiversion clangd / Result

## 最终状态
- 第六轮 namespace/lease/defer-initialized 加固已实现并通过 deterministic gate；真实防线
  spot-check 与 `389 refs/62 files` 核心价值回归均通过；待第六轮用户异构多路 Review 全票确认，
  尚未 merge。

## 测试情况
- Baseline：`159 passed in 3.74s`
- 修复前 UT：`168 passed in 3.16s`。
- 修复后最终 UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` → `172 passed in 3.00s`。
- 第三轮守卫加固后最终 UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` → `187 passed in 5.45s`。
- 第四轮守卫加固后最终 coverage gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch` → `217 passed in 5.29s`。
- 第五轮最终 coverage gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch`
  → `249 passed in 29.77s`（Python 3.12.3）。
- 第六轮最终 deterministic coverage gate：同命令 → `271 passed in 18.39s`（Python 3.12.3）。
- 修复后覆盖率：总计 92%（含 branch）；`api.py` 行覆盖 94%、综合 92%，`indexing.py` 行覆盖 91%、综合 89%，`clangd_adapter.py` 99%，`engine_version.py` 94%。
- 第四轮覆盖率：总计 92%（含 branch）；`api.py` 93%，核心 `indexing.py` 90%，`clangd_adapter.py` 99%，`engine_version.py` 94%。
- 第五轮覆盖率：总计 92%（含 branch）；`api.py` 92%，核心 `indexing.py` 90%，`clangd_adapter.py` 99%，`engine_version.py` 94%。
- 第六轮覆盖率：总计 92%（含 branch）；`api.py` 92%，核心 `indexing.py` 90%，`clangd_adapter.py` 99%，`engine_version.py` 94%。
- 静态 gate：ruff、black --check、带固定 tree-sitter binding 的 mypy codegraph、compileall、git diff --check 全绿。
- 新增覆盖：
  - LSP/serverInfo 版本提取与规范化；call graph 版本元数据成功/FAILED 路径。
  - `_looks_unsupported` 仅接受 method-not-found / JSON-RPC `-32601`，普通 unsupported 错误继续上抛。
  - stamp 匹配/缺失/不匹配、patch 精确匹配、建库成功写 stamp、无 stamp cache 不被普通建库自动认领。
  - 显式 `--stamp-existing-index` 三道检查、冲突 stamp 拒绝。
  - mismatch health/scope 降级、结构化 IssueCode、显式 symbol kind 不失真、已知 mismatch 不启动 clangd。
  - 冲突 stamp 在零 `.idx` 时仍优先 mismatch；非 idx 文件无 stamp 时 build preflight 仍拒绝自动认领。
  - 有 stamp 且当前版本不可探测时，自定义 factory 调用数为 0；probe 声明与实际 engine 不一致时启动后复核 fail-closed。
  - `build_index --inspect-only` 在 clangd 不可探测时输出结构化 `index_engine_unavailable` JSON。
  - builder 用 LSP serverInfo 实际版本在任何 TU 打开前复核 stamp 与 `--version`；撒谎 wrapper 的有 stamp/无 stamp 两种路径均 fail-closed。
  - `write_index_engine_version()` 仅允许排他首建或同版本幂等；冲突、损坏、目录及并发争用均不覆盖。
  - stamp 非法内容、目录、PermissionError 均为 `index_engine_stamp_invalid`，API prewarm/query factory 零调用，builder/CLI 均结构化阻断；missing stamp 的 API 保守可用路径不变。
  - 异版本 barrier builder 仅一个可在认领后打开 TU，输家在副作用前 mismatch；同版本 barrier builder 仅一个建库，输家结构化 `index_engine_build_in_progress`。
  - cache lock 排他性单独验证；另以同一 inode 的两个 fd 直接验证临时文件名 unlink 后 flock 仍然
    有效。第五轮不再依赖第四轮“失败回滚 committed stamp”的语义。
  - API/builder/CLI/direct-write 四条路径均拒绝有效及悬空 symlink；目录 mode 000 在 API/builder/CLI 均 fail-closed，factory/client 零调用。
  - `index_engine_build_in_progress` / `index_engine_stamp_write_failed` 均复用 `INDEX_UNKNOWN`，未新增冻结 IssueCode；CLI stamp PermissionError 输出结构化 JSON。
  - dirty/committed 双标记状态机：dirty 恒阻止 COMPLETE；同版本 stale dirty 可从零接管；异版本
    mismatch；dirty/committed 版本冲突 fail-closed；commit 中间崩溃由 dirty 优先。
  - cache-wide 独占/共享锁覆盖 builder、`--stamp-existing-index` 与 API engine 生命周期；API 与 builder
    交错时输家在副作用前被挡，同版本/异版本 builder 均只有一个启动 LSP 建库。
  - 未认证 cache 的 API adapter 强制 `background_index=false`，不仅 health/scope 降级，行为上也不写 cache。
  - builder 将 initialize request 与 `initialized` notification 拆开；dirty 发布和旧 shard 清理成功前
    不发送 `initialized`、不打开 TU。`run_background_index()` 明确定义为每次从零的完整建库入口。
  - canonical marker 严格解析、有效/悬空 symlink 拒绝、control temp 不参与 shard 扫描、陈旧 temp 清理、
    health/marker/lock 自身失败均按所有权未确认阻断。
  - 7 条 SIGKILL/优雅失败/commit-window/initialized/双 builder/API×builder 核心测试连续 30 轮全过。

## 三版本真机验证
- 真实版本专用目录：18/21/22 分别 3593/3595/3596 `.idx`；补 stamp 前均 UNKNOWN + `index_engine_unverified`，显式补 stamp 后均 COMPLETE。
- clangd 18.1.3：prewarm 1.702s；references 389/62；callers 387/62；callees FAILED + CALLHIERARCHY_UNSUPPORTED；call graph `engine_version=clangd 18.1.3`。
- clangd 21.1.1：prewarm 6.709s；references 389/62；callers 386/61；callees OK + 3 edges；call graph `engine_version=clangd 21.1.1`。
- clangd 22.1.8：prewarm 5.653s；references 389/62；callers 386/61；callees OK + 3 edges；call graph `engine_version=clangd 22.1.8`。
- 三版本：references 的 381 semantic + 8 candidates、`is_exhaustive=False`、不存在符号 UNRESOLVED/UNKNOWN 均一致；search/definition/references 的 `engine_version=None`。
- 三套版本专用 cache 查询前后 `.idx` 数量、总字节、最大 mtime 均不变。
- 故意错配 clangd 21 → clangd 18 cache：0.097s 返回 UNRESOLVED/UNKNOWN + INDEX_ENGINE_MISMATCH，detail=`index built by clangd 18.1.3; current engine clangd 21.1.1`；`.idx` 快照完全不变。
- 修复后复测错配 clangd 21 → clangd 18 cache：0.084s 返回 UNRESOLVED/UNKNOWN + INDEX_ENGINE_MISMATCH，`.idx` 快照完全不变。
- 所有权优先真机脚本：真实 clangd 21 面对临时“18 stamp + 零 idx”时 `exit_code=None/stable=False/index_engine_mismatch`；面对无 stamp 的 non-idx partial cache 时 `index_engine_unverified`，文件未改且未写 stamp。
- 有 stamp + probe unavailable：真实 18 cache 上 factory 调用数 0，返回 UNRESOLVED/UNKNOWN + `INDEX_UNKNOWN(current clangd version unavailable)`。
- 修复后三版本价值回归：18/21/22 references 均为 389/62；18 callees FAILED + unsupported，21/22 callees OK + 3 edges；三套 cache 快照不变。当前机器高负载下 18 冷态首次诚实降级为 2 refs/unknown，热态复跑恢复 389/62。
- 第三轮加固真机：撒谎 wrapper 的 `--version=99.99.99` 与 LSP serverInfo 实际版本不一致时，有 stamp 返回 mismatch、无 stamp 返回 `index_engine_version_inconsistent`；两者均未调用 `open_file`，既有 stamp 前后相同，无 stamp 不创建。
- 第三轮三版本回归：21/22 references 389/62、callees 3；18 高负载首轮 2 refs/unknown（未冒充项目级），热态复跑 389/62、callees FAILED + unsupported。18/21/22 cache 的 idx 数量/字节/max mtime 前后均不变；21 对 18 cache 0.085s mismatch 拦截且快照不变。
- 第四轮真实 builder 并发：clangd 21.1.1 与 22.1.8 barrier 同步 initialize，仅 21 打开 TU 并完成 1 shard，22 返回 `index_engine_mismatch`；两个 21.1.1 barrier 并发时仅一个打开 TU，另一个返回 `index_engine_build_in_progress`。两组 stamp 与 shard 均保持单一版本。
- pre-claim 触发点诊断：真实 clangd 21/22 完成 initialize 后强制等待 2s，fresh cache 在 claim/open_file 前两次观测均为 0 `.idx`；随后仍只有认领胜者打开 TU并写入分片。
- 第四轮三版本查询：18/21/22 prewarm `11.554s / 6.328s / 6.392s`；references 均 `389/62`、OK/complete、`is_exhaustive=False`，耗时 `3.742s / 3.623s / 3.624s`；18 callees FAILED + unsupported，21/22 callees OK + 3，engine_version 正确。三套 cache 快照均不变。
- 第四轮错配回归：clangd 21 对 18 cache 在 0.120s 内返回 UNRESOLVED/UNKNOWN + `INDEX_ENGINE_MISMATCH`，idx 数量/字节/max mtime 前后完全不变。
- 第五轮 SIGKILL：100-TU ARM 子集在 207 shards 时强杀，dirty=`clangd 21.1.1`、committed 缺失，
  health 为 UNKNOWN/build_in_progress；同版本不删目录直接接管，先清旧再建到 427 shards，8.599s
  后提交为 COMPLETE。1303-TU 全量重试的 809/1303 中间 plateau 被判 INCOMPLETE，未假认证。
- 第五轮优雅失败：50-TU ARM 子集首次 `max_wait=0` 在 357 shards 返回
  UNKNOWN/index_build_not_stable 且保留 dirty；同版本直接重试，7.861s 建到 446 shards 后才提交 COMPLETE。
- 第五轮真实 builder 竞态：21 vs 22 与 21 vs 21 各 5 轮，均只有一个 LSP/open_file，输家为
  `index_engine_build_in_progress`，最终 committed/shards 单一版本。
- 第五轮真实 API×builder 交错：API engine 持共享锁期间，builder 0.005s 返回
  `index_engine_build_in_progress`；阻断前后 shard 快照相同，API 查询返回 UNRESOLVED/unknown。
- 第五轮三版本回归：18/21/22 references 均 389/62、381 semantic + 8 candidates、
  `is_exhaustive=False`；18 callees FAILED + unsupported，21/22 callees OK + 3。21 对 18 cache
  0.152s mismatch 拦截，cache 快照不变。

## 代码
- 分支：`impl/change-6-multiversion`
- 对应 Git Commit：见该分支 HEAD；未 merge。

## Review
- Codex：完整 staged diff 自审与安全路径复核，无遗留 BLOCKER/MAJOR；实现中发现并修正了 mismatch 必须在默认 clangd 启动前拦截、显式 kind 不能因 health 降级而失真、stamp 后 CLI payload 需重扫分片等问题。
- Claude（gstack，只读）：完整 diff 调用超时后按 API/adapter 与 indexing/CLI 两个关注面拆分审查；共给出 5 条候选 finding，逐条以类型定义、冻结契约和已确认 stamp 语义反驳，无有效 BLOCKER/MAJOR。
- Claude（gstack，修复确认）：崩溃恢复后前两次调用未取得审查文本，均未计为通过；第三次聚焦所有权检查前移、stamped cache 版本探测 fail-closed、自定义 factory 与启动后二次复核，明确给出 `VERDICT: APPROVE`，无 BLOCKER/MAJOR。
- Kimi：CLI 可用但账户会员校验返回 HTTP 402，未获得审查输出，未计入通过数。
- 第三轮守卫复核：Codex 构造性穷举 API/builder/CLI 与 missing/invalid/conflict/unavailable/lying-probe/concurrent-create 状态，无遗留 BLOCKER/MAJOR。gstack Claude 完整 diff 180s 超时未计票，生产守卫聚焦重跑后明确 `VERDICT: APPROVE`；Kimi CLI 复探再次 180s 无输出，未计票。
- 第四轮：本地构造性测试与真机 gate 已完成；后续四路裁决发现第五轮问题并已据此加固。
- 第四轮 gstack Claude：完整 delta 与 production-code 聚焦 delta 两次调用均在 180s 内无审查文本，第二次 response 为空；均记能力失败/超时，不计票。
- 第五轮：本地构造性测试、30 轮稳定性与真机 gate 已完成；用户侧异构 review 尚未开始。任何
  能力失败或超时均不计票，用户要求全票前不得 merge。
- 第五轮 gstack Claude：完整 delta tool-less review 在 240s 内无 JSON/审查文本，按超时处理，
  不计 APPROVE。
- 第六轮：deterministic 自审和 30 轮并发稳定性已完成；真实 symlink、lock-path replacement、
  mismatch 与三版本 callees spot-check 通过。资源恢复后正式 CodeGraph API 连续三次复现
  `389/62`，现可进入用户异构多路 Review；Review 全票前仍不得 merge。

## 遗留问题 / 风险
- [第六轮真机 gate·已关闭] clangd 21 正式 CodeGraph API 连续三次 references 均为
  `389/62`、`381 semantic + 8 candidates`、`OK/complete/indexed_project`、`is_exhaustive=False`，
  耗时 `2.930s / 2.953s / 2.925s`；3595 个分片的数量/字节/max-mtime 前后不变。
- 本阶段按冻结设计使用完整 patch 版本精确匹配；是否允许同 major 的索引兼容留二期，不在本实现放宽。
- `--stamp-existing-index` 是显式人工 provenance attestation：它验证 CDB/分片 health、当前 clangd 版本、冲突 stamp，但无法从无 stamp 分片反推历史 builder；来源不确定时必须空目录重建。
- 原始 `rw_arm` cache 曾被 clangd 21 接触并从 3593 增至 3614 分片，属于已污染来源，禁止使用 `--stamp-existing-index` 追认。
- 不存在符号的 `workspace/symbol` 真机耗时为 18=24.672s、21=27.032s、22=29.295s；诚实性正确但性能值得后续独立 harden。
- 本实现涉及索引诚实性防线，必须通过用户异构多路 Review 后才能 merge。

## 下一步
- commit + push 第五轮守卫修复，供用户侧异构 review 按“任何路径 × 任何 marker 状态 × 任何并发
  交错”构造性复核；全票通过后才可等待 merge 收口。
