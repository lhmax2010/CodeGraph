# Stage 02 - Routing / Result

## 最终状态
已 Merge。P2 最终 review 通过（三路 + 人工核实）；按用户指令，本项目只 `git push`，不创建 PR。

## 测试情况
- UT 结果：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `80 passed in 0.06s`
- 覆盖率（行/分支）：`PYTHONPATH=.:tools /home/linhao/.local/bin/uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `80 passed in 0.19s`，total 96%，`codegraph/routing.py` 95%
- 确定性检查：
  - `python3 -m compileall -q codegraph tools tests`：通过，无输出。
  - `/home/linhao/.local/bin/uv tool run ruff check .`：All checks passed。
  - `/home/linhao/.local/bin/uv tool run black --check .`：13 files would be left unchanged。
  - `/home/linhao/.local/bin/uv tool run mypy codegraph`：Success, no issues in 7 source files。
- 补测内容：Phase 2 路由测试覆盖 QR1-9、降级真值表、混合结果、空结果分支、engine exception、fallback 阈值过滤、QR7 `{may,n/a}`、QR7 `consumer_warning=="not_evidence"`、CallEdgeResult 候选无损降级、ImpactResult 不进候选、syntax helper 缺失保守降级、index_health 结构化 notes。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）
- Baseline：`9e1157f`
- P2 代码最终提交：`b595157 [Phase 2] fix: preserve call edge candidates and enforce not_evidence`
- Checkpoint：`checkpoint/phase_2_routing`

## 遗留问题 / 风险
- `docs/design_changes/change_3.md` 已应用到 design.md v1.4.3 与代码：CandidateData 支持 CallEdgeResult；QR7 运行时强制 `consumer_warning=="not_evidence"`。
- `docs/design_changes/change_4.md` 已登记，不阻塞 P2 merge，但 P6 前必须由 design owner 决策：P4 syntax helper 缺失时的降级策略与 MACRO symbol_kind 是否一律降级。
- 当前未接真实 clangd/tree-sitter adapter；按 Phase 边界由 P3/P4/P6 后续集成。

## 下一阶段计划
- 进入后续 Phase。P6 前先处理 `change_4.md` 的设计决策。
