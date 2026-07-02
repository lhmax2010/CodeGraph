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

## 2026-07-02 - Claude review after prewarm/timeout fix

### 输入范围

- Review mode：`gstack-claude` 等价流程，嵌套 `claude -p`，`--disable-slash-commands` 且 `--tools ""`。
- 外发前做了范围收敛：只发送 `codegraph/api.py`、`codegraph/engines/protocol.py`、`codegraph/engines/clangd_adapter.py`、`tests/test_api.py`、`tests/test_phase1_metadata.py` 的代码/测试 diff；未发送 `.dev_memory` 里的真机绝对路径和日志。
- 聚焦问题：
  - 显式 prewarm 只能焐 cache，后续查询不得跳过 `_warm_background_index`。
  - `prewarm_index_ready_timeout` 与用户查询 `index_ready_timeout` 分开生效。
  - readiness 必须证明当前 clangd 进程消费了全局索引。
  - `background_index=False` 或未 ready 时不得借 P5 `complete` 做项目级 `not_found`。
  - `register_build_config(config, prewarm=True)` 不应破坏既有 `None` 返回契约。

### 首轮结论

Claude 首轮指出一个属实 BLOCKER 和两个属实 MAJOR/兼容风险：

- BLOCKER：配置了 `index_ready_probe_symbol` 但未配置 `index_ready_probe_path_suffix` 时，`_index_ready_probe_matches()` 会把单 TU/header 中的同名 sentinel 当作 ready。
  - 处理：`_warm_background_index()` 在缺 suffix 时直接返回 not-ready；`_index_ready_probe_matches()` 也 fail-closed；新增缺 suffix 不轮询、不传 `complete` 的测试。
- MAJOR：`search_symbol` 先 exact 分页再用当前页长度当 `total_hits`，offset 越界时可能把“有总命中但当前页为空”送入 `not_found`。
  - 处理：`_exact_symbol_observation()` 返回 `(page, exact_total)`；`route_observation()` 只有 `total_hits is None or total_hits == 0` 才允许 not_found；新增 offset 保留 total 与空页不 not_found 测试。
- 兼容风险：`ClangdAdapterConfig` 把 `background_index` 插到 `extra_args` 前面，会破坏旧的第三位置参数语义。
  - 处理：字段顺序恢复为 `compile_commands_dir, clangd_path, extra_args, background_index`；新增位置参数兼容测试。
- API 兼容风险：`register_build_config(..., prewarm=True)` 从 `None` 改成 `bool`。
  - 处理：恢复 `None` 返回；`prewarm_build_config()` 保持返回 `bool`；测试改为断言副作用而非返回值。

Claude 另提到 `workspace/symbol` exact 结果可能受 clangd fuzzy 排序窗口影响。该点是 clangd LSP 能力限制，adapter 已在 clangd 返回后本地 exact filter；P6 继续登记为后续可观察风险，不作为本轮 blocking fix。

### Focused Follow-Up

对上述 follow-up diff 复跑 Claude 复核。结论：`NO BLOCKER/MAJOR`。

- Claude 确认四项修复均朝 fail-safe 方向收敛：
  - `register_build_config` 恢复 `None` 契约。
  - readiness 同时要求 symbol 和 suffix，缺任一项都只能降 `unknown/current_tu`。
  - exact 总数与 page 分离，`total_hits>0` 的空页不会再被解释为不存在。
  - `ClangdAdapterConfig` 第三位置参数恢复为 `extra_args`。
- Claude MINOR：确认仓库无 `ClangdAdapterConfig(dir, path, True)` 这种过渡期位置参数调用，并建议运行时拒绝该误写。
  - 处理：`rg "ClangdAdapterConfig\\(" codegraph tests tools docs .dev_memory` 确认无位置参数 `background_index` 调用；新增 `__post_init__` 校验 `extra_args` 必须是 `tuple[str, ...]`，误写会直接 `TypeError`。
- Claude MINOR：补一个 `get_definition` legitimate not_found 仍可达的断言，确认 router 的 `total_hits>0` guard 没误伤默认 `total_hits=0` 路径。
  - 处理：新增 ready+complete+空 definition 仍返回 `NOT_FOUND` 的测试。
- Claude NIT：`_index_ready_probe_matches(suffix=None)` 只有间接覆盖。
  - 处理：新增直接测试。

### Gate

- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `138 passed in 2.05s`。
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `138 passed`，total `93%`。
- `.venv/bin/ruff check .` -> All checks passed。
- `.venv/bin/black --check .` -> 22 files unchanged。
- `.venv/bin/mypy codegraph` -> Success。
- `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过。

## 2026-07-02 - Four-way review follow-up BLOCKER

用户异构四路 review 后，Codex 抓到一个属实 BLOCKER：`search_symbol` 的 `total_hits` 是
`engine_limit=max(100, limit+offset)` 返回窗口内的 exact 计数，不是全局真实 total。若 clangd
`workspace/symbol` 前 100 条均为 fuzzy 近似、真实 exact 排在第 101 条之后，窗口内 exact 为 0，
P2 会在 ready+complete 下把真实存在的符号误判为 `not_found`。

### 处理

- 选择方案 A：窗口可能截断时禁止项目级 `not_found`。
- 实现：P6 API 层记录原始 `workspace/symbol` 返回数；当返回数 `>= engine_limit` 且窗口内 exact
  为 0 时，本次查询不再把 ready+complete 传给 P2，而是降为 `unknown/current_tu`，结果为
  `UNRESOLVED`。
- 边界：不再改 P2 `routing.py`；`route_observation` 的 QR/状态机保持不变。
- 回归：新增“前 100 条 fuzzy、exact 在第 101 条之外”的 fake engine 测试，断言不是 `not_found`。

### Gate

- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_api.py -q` -> `23 passed`。
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `14 passed`。
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `139 passed in 3.70s`。
- coverage -> `139 passed`，total `93%`。
- ruff / black --check / mypy / compileall / diff-check 全绿。

### 状态

该修复是安全逻辑修改，仍需用户异构多路 review 复核；复核前不进入 P6 真机验收。
