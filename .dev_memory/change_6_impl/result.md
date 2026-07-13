# Change 6 Implementation - Multiversion clangd / Result

## 最终状态
- 待用户核对；代码、deterministic gate、三版本真机验证与本地双模型异构 Review 已完成，尚未 merge。

## 测试情况
- Baseline：`159 passed in 3.74s`
- 最终 UT：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` → `168 passed in 3.16s`。
- 覆盖率：`168 passed`；总计 95%，`api.py` 95%，`indexing.py` 91%，`clangd_adapter.py` 99%，`engine_version.py` 92%。
- 静态 gate：ruff、black --check、带固定 tree-sitter binding 的 mypy codegraph、compileall、git diff --check 全绿。
- 新增覆盖：
  - LSP/serverInfo 版本提取与规范化；call graph 版本元数据成功/FAILED 路径。
  - `_looks_unsupported` 仅接受 method-not-found / JSON-RPC `-32601`，普通 unsupported 错误继续上抛。
  - stamp 匹配/缺失/不匹配、patch 精确匹配、建库成功写 stamp、无 stamp cache 不被普通建库自动认领。
  - 显式 `--stamp-existing-index` 三道检查、冲突 stamp 拒绝。
  - mismatch health/scope 降级、结构化 IssueCode、显式 symbol kind 不失真、已知 mismatch 不启动 clangd。

## 三版本真机验证
- 真实版本专用目录：18/21/22 分别 3593/3595/3596 `.idx`；补 stamp 前均 UNKNOWN + `index_engine_unverified`，显式补 stamp 后均 COMPLETE。
- clangd 18.1.3：prewarm 1.702s；references 389/62；callers 387/62；callees FAILED + CALLHIERARCHY_UNSUPPORTED；call graph `engine_version=clangd 18.1.3`。
- clangd 21.1.1：prewarm 6.709s；references 389/62；callers 386/61；callees OK + 3 edges；call graph `engine_version=clangd 21.1.1`。
- clangd 22.1.8：prewarm 5.653s；references 389/62；callers 386/61；callees OK + 3 edges；call graph `engine_version=clangd 22.1.8`。
- 三版本：references 的 381 semantic + 8 candidates、`is_exhaustive=False`、不存在符号 UNRESOLVED/UNKNOWN 均一致；search/definition/references 的 `engine_version=None`。
- 三套版本专用 cache 查询前后 `.idx` 数量、总字节、最大 mtime 均不变。
- 故意错配 clangd 21 → clangd 18 cache：0.097s 返回 UNRESOLVED/UNKNOWN + INDEX_ENGINE_MISMATCH，detail=`index built by clangd 18.1.3; current engine clangd 21.1.1`；`.idx` 快照完全不变。

## 代码
- 分支：`impl/change-6-multiversion`
- 对应 Git Commit：见该分支 HEAD；未 merge。

## Review
- Codex：完整 staged diff 自审与安全路径复核，无遗留 BLOCKER/MAJOR；实现中发现并修正了 mismatch 必须在默认 clangd 启动前拦截、显式 kind 不能因 health 降级而失真、stamp 后 CLI payload 需重扫分片等问题。
- Claude（gstack，只读）：完整 diff 调用超时后按 API/adapter 与 indexing/CLI 两个关注面拆分审查；共给出 5 条候选 finding，逐条以类型定义、冻结契约和已确认 stamp 语义反驳，无有效 BLOCKER/MAJOR。
- Kimi：CLI 可用但账户会员校验返回 HTTP 402，未获得审查输出，未计入通过数。

## 遗留问题 / 风险
- 本阶段按冻结设计使用完整 patch 版本精确匹配；是否允许同 major 的索引兼容留二期，不在本实现放宽。
- `--stamp-existing-index` 是显式人工 provenance attestation：它验证 CDB/分片 health、当前 clangd 版本、冲突 stamp，但无法从无 stamp 分片反推历史 builder；来源不确定时必须空目录重建。
- 不存在符号的 `workspace/symbol` 真机耗时为 18=24.672s、21=27.032s、22=29.295s；诚实性正确但性能值得后续独立 harden。
- 本实现涉及索引诚实性防线，必须通过用户异构多路 Review 后才能 merge。

## 下一步
- commit + push 实现分支供用户核对；根据核对结果修复或进入 merge 收口。
