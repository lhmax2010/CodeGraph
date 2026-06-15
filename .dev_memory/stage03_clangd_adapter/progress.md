# Stage 03 - Clangd Adapter / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 3 开 stage baseline 取 `main@e87543d`，从该提交新建 `phase/3-clangd-adapter`。
  - 原因：stage02_routing 已 Merge，`main` 干净且 P2 baseline 80 tests 全过。
  - 排除的方案：从旧 `phase/2-routing` 继续开发。该方案会绕开已 Merge 的 checkpoint 与 INDEX 状态。
- 决策：Phase 3 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P3 首次接真实 clangd 子进程/LSP，涉及异步诊断、超时、callHierarchy 能力兼容与小型 CDB 真集成。
  - 排除的方案：按普通风险推进。该方案低估了真实引擎边界和超时/生命周期对后续 P6/P8 的影响。
- 决策：P3 只产 observation，不写任何 credibility/resolved/relation/certainty 判断。
  - 原因：可信度解释属于 P2 路由层；adapter 只报告 clangd 返回了什么和诊断事实。
  - 排除的方案：在 adapter 内直接把空结果解释为 not_found 或把调用边标 must。该方案越界并会破坏分层。
- 决策：callers/callees 必须用 clangd callHierarchy，不用 references+AST 近似推导。
  - 原因：设计明确要求调用关系来自 clangd callHierarchy；近似图会产出不可信关系。
  - 排除的方案：用 references 搜调用点再猜 caller/callee。该方案违反 P3/P8 contract。
- 决策：P3 严格按 P2 已 Merge 的 `EngineObservationResult` 接缝填字段：`locations`、`references`、`call_edges`、`diagnostics.file_not_found`、`diagnostics.fatal`、`diagnostics.soft`、`symbol_ambiguous`、`index_scope_known`。
  - 原因：P2 `routing.py` 直接消费这些字段；字段名、类型或语义错位会让路由层接不上。
  - 排除的方案：在 P3 自创字段或提前填 credibility/status。该方案越界且破坏 P2/P3 分层。
- 决策：clangd 空结果只作为空 observation 返回，P3 不解释成 `not_found`。
  - 原因：空返回可能是真不存在、索引未覆盖、依赖缺失或其他上下文问题；只有 P2 能综合 dependency/index_health 做结论。
  - 排除的方案：在 adapter 内把空 definition/references 解释为 not_found。该方案会制造虚假否定风险。
- 决策：P3 adapter 直接复用 `tools.verify_clangd.LSPClient` / `path_to_uri`，通过 client factory 注入假客户端做单测。
  - 原因：`verify_clangd.py` 已验证 stdlib stdio LSP、request timeout、diagnostics 收集与 shutdown；P3 只封装查询与结果转换。
  - 排除的方案：在 `clangd_adapter.py` 重新实现 LSP framing/reader/request loop。该方案违反复用资产约束，并扩大真实引擎风险面。
- 决策：`clangd_adapter.py` 用动态导入加载 `tools.verify_clangd`，避免 `mypy codegraph` 因静态 import 追进工具脚本内部实现。
  - 原因：P3 仍复用 verify asset；但类型门针对 `codegraph` 核心模块，不应因为 adapter import 把历史工具脚本变成核心 mypy 检查对象。
  - 排除的方案：直接静态 import `tools.verify_clangd`。该方案会让 mypy 报告工具脚本中 `subprocess.PIPE` 的可选 stdin 类型问题，扩大本阶段改动范围。
- 决策：真实 clangd 集成测试使用临时单文件 CDB，覆盖 definition / references / callHierarchy。
  - 原因：P3 可用小型 CDB 验证真实 LSP，不依赖 P5 离线建库；callHierarchy 是硬要求，必须实际跑一次。
  - 排除的方案：只用 fake LSP 单测。该方案无法证明本机 clangd 18.1.3 的真实能力和返回形状。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage03_clangd_adapter` 为当前活跃 stage，记录 baseline commit。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/plan.md`
  - 改动内容：记录 Phase 3 目标、范围边界、计划步骤、baseline、环境和风险档候选。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 3 收尾时填写。

## 进度日志
- [2026-06-15] 读取 `AGENTS.md`、`docs/design.md` v1.4.3、`docs/design_changes/change_1/2/3/4.md`、`.dev_memory/INDEX.md`、stage01/stage02 result、stage02 plan/progress、review 记录和 `tools/verify_clangd.py`；确认 `change_4` 是 P6 前的 syntax-helper 设计决策，不属于 P3。
- [2026-06-15] 确认 stage02 已 Merge；`main` 位于 `e87543d [Phase 2] docs: close routing stage` / `checkpoint/phase_2_routing`。
- [2026-06-15] clangd 环境预检：`/usr/bin/clangd`，Ubuntu clangd `18.1.3 (1ubuntu1)` 可用。
- [2026-06-15] 在 `main@e87543d` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `80 passed in 0.07s`。
- [2026-06-15] 从 `main@e87543d` 新建分支 `phase/3-clangd-adapter`。
- [2026-06-15] 创建 `.dev_memory/stage03_clangd_adapter/` 计划与进度骨架；等待风险档与 restate gate 确认后再实现。
- [2026-06-15] 开发者确认 Phase 3 高风险档与实现计划；动手前核对 P2 `routing.py` 实际消费 observation 字段，确认 P3 只产观察事实，不判断 not_found。
- [2026-06-15] 实现 `codegraph/engines/clangd_adapter.py` 与 `tests/test_clangd_adapter.py`；P3 单测含 fake LSP 和真实 clangd 小 CDB，`PYTHONPATH=.:tools python3 -m pytest tests/test_clangd_adapter.py -q` -> `8 passed in 0.13s`。
- [2026-06-15] 全量测试：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `88 passed in 0.18s`。
- [2026-06-15] 静态 gate：`uv tool run ruff check .` -> `All checks passed!`；`uv tool run black --check .` -> `15 files would be left unchanged`；`uv tool run mypy codegraph` -> `Success: no issues found in 8 source files`。
- [2026-06-15] 覆盖率：`PYTHONPATH=.:tools uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `88 passed in 0.34s`，total coverage 97%，`codegraph/engines/clangd_adapter.py` coverage 100%。
- [2026-06-15] 编译检查：`python3 -m compileall -q codegraph tools tests` 通过，无输出。
