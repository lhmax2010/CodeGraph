# Stage 04 - Treesitter / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 4 开 stage baseline 取 `main@46ed936`，从该提交新建 `phase/4-treesitter`。
  - 原因：stage03_clangd_adapter 已 Merge，change_4 v1.4.4 已落库并作为 P4 基线。
  - 排除的方案：从 `checkpoint/phase_3_clangd_adapter` 开发。该方案会漏掉 v1.4.4 设计基线提交。
- 决策：Phase 4 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P4 引入真实 tree-sitter、实现 P6 前置 syntax helper，并需外科式修改已 Merge 的 P2 宏短路。
  - 排除的方案：按普通风险推进。该方案低估了 P2 回改和要素2误判的影响。
- 决策：P4 起所有 gate 统一使用项目本地 `.venv/bin/python`。
  - 原因：tree-sitter binding 固定安装在 `.venv`，系统 Python 受 PEP 668 管理且不能直接 import tree-sitter；统一环境可避免 review 复现时出现系统 Python 假失败。
  - 排除的方案：继续混用系统 `python3` 与临时 `uv tool run --with`。该方案会让 P4 真集成测试环境漂移。
- 决策：先做 P2 外科回改，再立即跑 `tests/test_phase2_routing.py`。
  - 原因：`routing.py` 已 Merge 且是核心层；change_4 只允许删除 `symbol_kind==MACRO` 一个短路条件，必须先证明 QR1-9/状态机/降级真值表未破。
  - 排除的方案：等 P4 adapter 写完后再一起验。该方案会把 P2 回归问题和 P4 新代码问题混在一起。
- 决策：`TreeSitterProvider` 提供完整 `Candidate`，并让 P2 继续通过 `_normalize_fallback_candidate()` 重造 credibility。
  - 原因：P1 协议要求 provider 返回候选；P2 当前消费模式会保留 `symbol_kind` 和 `relevance_score` 并统一套容器侧护栏，P4 不需要调协议或绕过路由。
  - 排除的方案：修改 SyntacticProvider 协议传入 query_kind/kind_filter 给 `candidates_near()`。该方案会扩大已冻结接口面。
- 决策：`create_treesitter_provider()` 在 binding 不可得时返回 `None`，模块 import 本身不崩溃。
  - 原因：change_4 的不可得路径应让调用方传 `syntactic_provider=None`，由 P2 `provider is None -> True` 保守降级和 fallback notes 表达风险。
  - 排除的方案：模块顶层 import 失败直接抛。该方案会让服务启动失败，无法进入既有降级路径。
- 决策：syntax helper 对 `preproc_def` / `preproc_function_def` 先处理宏定义名例外，再处理一般 `preproc_*` 盲区。
  - 原因：`#define` 宏定义名本身是真实源码，应非伪位置；宏体 `preproc_arg` 等生成/展开区域才标盲区。
  - 排除的方案：所有 `preproc_*` 祖先一律盲区。该方案会重新误杀宏定义查询，违反 change_4。
- 决策：`is_preprocessor_location()` 在文件无法读取/解析时返回 `True`。
  - 原因：`False` 表示“确认非宏伪位置”，会让 P2 保留 OK；无法解析属于要素2无法确认，应按 change_4 安全原则保守降级。
  - 排除的方案：继续返回 `False`。该方案会让 clangd 指向已删除或不可读文件的位置误升为可信语义结果。
- 决策：清理 `_has_preprocessor_blind_spot()` 的 `symbol_kind` 死参，但保留 `item_kind` 局部变量。
  - 原因：删 MACRO 短路后 blind-spot helper 不再需要 symbol_kind；但 `item_kind` 仍用于 semantic/candidate credibility，不能一并删除。
  - 排除的方案：删除 `item_kind`。该方案会丢失结果真实 symbol_kind 标注。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage04_treesitter` 为当前活跃 stage，更新设计基线到 v1.4.4。
- 文件/模块：`.dev_memory/stage04_treesitter/plan.md`
  - 改动内容：记录 Phase 4 目标、范围边界、计划步骤、baseline、tree-sitter 环境与风险档候选。
- 文件/模块：`.dev_memory/stage04_treesitter/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage04_treesitter/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 4 收尾时填写。

## 进度日志
- [2026-06-17] 读取 `docs/design.md` v1.4.4、`docs/design_changes/change_4.md`、`.dev_memory/INDEX.md`、stage01/stage02/stage03 result、P4/P6 设计章节、P1/P2 接缝代码；确认 P4 要实现 tree-sitter provider + syntax helper，并只精确移除 P2 的 `symbol_kind==MACRO` 短路。
- [2026-06-17] 当前 `main` 位于 `46ed936 [design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`，工作树干净。
- [2026-06-17] 在 `main@46ed936` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.21s`。
- [2026-06-17] tree-sitter 环境预检：裸 `python3` 不能 import `tree_sitter`；`uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4` 可 import；微型 C parse 能识别 `preproc_def` / `preproc_arg`。
- [2026-06-17] 从 `main@46ed936` 新建分支 `phase/4-treesitter`。
- [2026-06-17] 创建 `.dev_memory/stage04_treesitter/` 计划与进度骨架；等待风险档与 restate gate 确认后再实现。
- [2026-06-17] 环境确认：系统 `/usr/bin/python3` 受 PEP 668 管理，`python3 -m pip install --dry-run tree-sitter...` 被拒；`python3 -m venv .venv` 因缺 `ensurepip` 失败；改用 `uv venv --allow-existing --seed .venv` 建立项目本地 venv 并安装 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4`、`pytest`、`pytest-cov`。
- [2026-06-17] `.venv/bin/python` 直接 import tree-sitter 成功，微型 C parse 识别 `preproc_def` / `preproc_arg`；`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `90 passed in 0.24s`。
- [2026-06-17] 开始实现前确认：P4 所有 pytest/coverage gate 使用 `.venv/bin/python`；ruff/black/mypy 使用 `.venv` 中工具或等价可见 tree-sitter 的环境。
- [2026-06-17] P2 外科回改：`codegraph/routing.py::_has_preprocessor_blind_spot()` 仅删除 `symbol_kind == SymbolKind.MACRO` 条件，保留 `syntactic_provider is None -> True`；立即跑 `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `13 passed in 0.02s`。
- [2026-06-17] 实现 `codegraph/engines/treesitter_adapter.py`：真实 tree-sitter C/C++ parser、候选抽取、评分、position-based preproc helper、安全 factory。新增 `tests/test_treesitter_adapter.py`，覆盖 binding 不可得、真实候选评分、helper 的宏定义/宏体两类位置、route_observation 集成降级。
- [2026-06-17] 补宏定义可 OK 的 P2 回归测试；`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `14 passed in 0.15s`。
- [2026-06-17] P4 专项：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_treesitter_adapter.py -q` -> `5 passed in 0.02s`。
- [2026-06-17] 全量测试：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `96 passed in 0.19s`。
- [2026-06-17] 静态 gate（均在 `.venv`）：`.venv/bin/ruff check .` -> `All checks passed!`；`.venv/bin/black --check .` -> `17 files would be left unchanged`；`.venv/bin/mypy codegraph` -> `Success: no issues found in 9 source files`。
- [2026-06-17] 覆盖率：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `96 passed in 0.33s`，total coverage 92%，`codegraph/engines/treesitter_adapter.py` coverage 82%。
- [2026-06-17] 编译检查：`.venv/bin/python -m compileall -q codegraph tools tests` 通过；系统 Python smoke：`tree_sitter_available()` 为 False、`create_treesitter_provider(...)` 返回 None，确认无 binding 时 import 不崩溃。
- [2026-06-17] P4 review fix：修复 `is_preprocessor_location()` 文件无法解析时误返回 `False` 的 MAJOR，改为 `True` 保守降级；补不可解析文件 location 的 route_observation 回归。顺手删除 `_has_preprocessor_blind_spot()` 的 `symbol_kind` 死参和调用实参，确认 `item_kind` 仍用于 credibility。
- [2026-06-17] P4 review fix gate：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `14 passed in 0.02s`；`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_treesitter_adapter.py -q` -> `6 passed in 0.03s`；全量 `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.19s`；`.venv/bin/ruff check .` -> `All checks passed!`；`.venv/bin/black --check .` -> `17 files would be left unchanged`；`.venv/bin/mypy codegraph` -> `Success: no issues found in 9 source files`；coverage `97 passed in 0.34s`，total 93%，`codegraph/engines/treesitter_adapter.py` 83%；`.venv/bin/python -m compileall -q codegraph tools tests` 通过。
