# Stage 02 - Routing / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 2 开 stage baseline 取 `main@9e1157f`，从该提交新建 `phase/2-routing`。
  - 原因：stage01_metadata 已 Merge，`main` 干净且 P1 baseline 67 tests 全过。
  - 排除的方案：从旧 `phase/1-metadata` 继续开发。该方案会绕开已 Merge 的 main 收尾状态。
- 决策：Phase 2 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P2 同时承载路由状态机、降级真值表、四道护栏触发和 QR1-9 容器校验，组合面明显大于 P1；但仍可用协议桩隔离验证。
  - 排除的方案：简单按设计 §7 预估规模归为普通风险。该方案低估了 QR/路由交叉错误对后续阶段的扩散风险。
- 决策：QR1 在容器校验中按双向约束实现，状态机代码严格分离“非空但不可信”和“空结果”两条分支。
  - 原因：`OK` 无结果与“有结果却标 UNRESOLVED/NOT_FOUND”都是自相矛盾容器；非空全不可信若误入空结果分支，会制造虚假否定。
  - 排除的方案：只检查 `OK => semantic_results` 或把全不可信与空结果共用 not_found 判定。前者漏掉反向矛盾，后者违反 §4.4 防虚假否定核心。
- 决策：P2 测试桩必须覆盖缺要素1/2/4、全不可信、混合、空返回、引擎异常七类场景。
  - 原因：P2 不接真实 P3/P4 adapter，降级真值表只能靠桩覆盖；桩能力不足会导致核心状态机未被测试到。
  - 排除的方案：只测最终 QueryStatus。该方案无法证明降级 note、候选通道、混合不丢弃和分支隔离正确。
- 决策：`routing.py` 暴露 `check_query_result_invariants()`、`validate_query_result()`、`route_engine_call()`、`route_observation()` 四个最小入口，不实现 P6 对外 API。
  - 原因：Phase 2 只交付路由核心与容器校验；具体 `search_symbol/get_definition/...` 接口编排归 P6。
  - 排除的方案：在 P2 直接实现 public API wrapper。该方案会提前进入 P6 范围。
- 决策：tree-sitter fallback 候选进入路由后统一 normalize build_config/query_kind/relation/certainty，而不是信任测试桩原样正确。
  - 原因：QR6/QR7/QR8 是 P2 的强制容器闸门；P2 应保证返回前候选满足 `{may,n/a}`、`syntactic`、build_config 一致。
  - 排除的方案：完全信任 `SyntacticProvider` 输出。该方案会让坏候选绕过路由层责任，直到容器校验时报错，降低 fallback 可用性。
- 决策：`background-index + index_scope=global` 的空结果不构造 not_found，保守返回 `UNRESOLVED`。
  - 原因：INV14 矩阵允许 `background-index` 的 negative_scope 只能是 `current_tu`，而 `current_tu` 负证明不能挂在 `global` index_scope 上；该组合不应制造非法 not_found。
  - 排除的方案：强行构造 global/indexed_project not_found。该方案会违反 P1 INV14 矩阵或 background-index 钳制。
- 决策：实现与测试从初版约 1507 物理行压缩到约 1118 物理行后停止继续压缩，保留可读性与关键路径覆盖。
  - 原因：继续压缩需要把路由状态机和测试场景过度折叠，降低三路 review 可读性；当前 `routing.py` 代码语句覆盖 94%，关键分支均有测试。
  - 排除的方案：为贴近 800 行预算继续做高密度代码/测试压缩。该方案会牺牲可维护性，且 P2 已被确认高风险、需要清晰 review 面。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage02_routing` 为当前活跃 stage，记录 baseline commit。
- 文件/模块：`.dev_memory/stage02_routing/plan.md`
  - 改动内容：记录 Phase 2 目标、范围边界、计划步骤、baseline 与风险档候选。
- 文件/模块：`.dev_memory/stage02_routing/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage02_routing/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 2 收尾时填写。
- 文件/模块：`codegraph/routing.py`
  - 改动内容：新增 QR1-9 容器校验、QueryResult 双校验、engine exception 分支、非空结果降级真值表、空结果 not_found/unresolved 分支、fallback 阈值过滤。
- 文件/模块：`tests/test_phase2_routing.py`
  - 改动内容：新增 Phase 2 路由与容器校验测试，覆盖 QR1 双向、QR3-9、缺要素1/2/4、全不可信、混合、空返回、异常、fallback 阈值和 QR7 `{may,n/a}`。

## 进度日志
- [2026-06-13] 读取 `docs/design.md` v1.4.2 与 `.dev_memory/INDEX.md`，确认 stage01 已 Merge、Phase 2 未启动。
- [2026-06-13] 在 `main@9e1157f` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q`，结果 `67 passed in 0.07s`。
- [2026-06-13] 从 `main@9e1157f` 新建分支 `phase/2-routing`。
- [2026-06-13] 创建 `.dev_memory/stage02_routing/` 计划与进度骨架；等待 restate gate 确认后再实现。
- [2026-06-13] 开发者确认 Phase 2 高风险档与实现计划；动手前补充 QR1 双向、非空/空分支分离、测试桩场景清单。
- [2026-06-13] 实现 `codegraph/routing.py` 与 `tests/test_phase2_routing.py`；P2 单测 `PYTHONPATH=.:tools python3 -m pytest tests/test_phase2_routing.py -q` 通过 10 tests。
- [2026-06-13] 全量测试：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `77 passed in 0.06s`。
- [2026-06-13] 静态 gate：`uv tool run ruff check .` -> `All checks passed!`；`uv tool run black --check .` -> `13 files would be left unchanged`；`uv tool run mypy codegraph` -> `Success: no issues found in 7 source files`。
- [2026-06-13] 覆盖率：`PYTHONPATH=.:tools uv tool run --with pytest-cov pytest --cov=codegraph --cov-branch tests/ -q` -> `77 passed in 0.22s`，total coverage 96%，`codegraph/routing.py` coverage 94%。
