# Phase 6 Review Result

## 2026-07-01 - Claude second opinion after BLOCKER fixes

### 输入范围

- Review mode：`gstack-claude` 等价流程，嵌套 `claude -p`，`--disable-slash-commands` 且 `--tools ""`。
- 为避免外发本机真机路径/日志，未发送 `.dev_memory`；发送的是 P6 blocker 修复相关的 `codegraph/api.py` 与 `tests/test_api.py` 关键摘录。
- 聚焦问题：
  - `background_index=False` 不得用 P5 `complete` 做项目级 `not_found` 负证明。
  - background-index ready 不得由用户查询 symbol 的单 TU/header 命中误触发。
  - `search_symbol` 精确过滤应先于用户侧 `limit/offset` 分页。

### 结论

Claude 判定：`NO BLOCKER/MAJOR`。

- BLOCKER 1 修复充分：`_effective_health()` 与 `_effective_index_scope()` 都要求 `background_index` 且 `index_ready`；`background_index=False` 降为 `UNKNOWN/CURRENT_TU`，测试覆盖空结果必须为 `UNRESOLVED/unknown`。
- BLOCKER 2 修复充分：`_warm_background_index()` 轮询的是配置化 sentinel，不再使用用户查询 symbol；测试覆盖目标/header 命中不能触发 ready。
- 精确过滤修复充分：`_exact_symbol_observation()` 先过滤 exact，再按用户 `offset/limit` 切片；engine 侧改为从 offset 0 过量拉取。

### 发现与处理

- MINOR：`_warm_background_index()` 的 `symbol` 参数未使用，容易误导读者以为 ready 仍受查询 symbol 影响。
  - 处理：已删除该死参和调用处实参。
- NIT：ready 后 `_health_after_warm()` 会重新读取一次 index health，存在轻微重复 IO。
  - 处理：不影响正确性，暂不扩范围。
- NIT：`_semantic_search_limit()` 目前为 `max(100, limit + offset)`；若极端场景中 fuzzy 结果超过过量窗口，仍可能漏掉更靠后的 exact。
  - 处理：P6 已修复原先“先分页再 exact”的主要问题；该极端排序问题登记为后续可观察项，不阻塞本轮安全修复。
