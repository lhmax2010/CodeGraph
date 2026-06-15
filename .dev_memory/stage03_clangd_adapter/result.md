# Stage 03 - Clangd Adapter / Result

## 最终状态
进行中（开 stage / 待确认风险档与 restate）。

## 测试情况
- Baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `80 passed in 0.07s`。
- 覆盖率：尚未运行（未开始实现）。
- 补测内容：待实现后填写。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`e87543d [Phase 2] docs: close routing stage`。
- 当前分支：`phase/3-clangd-adapter`。
- 对应 Git Commit：待实现后填写。

## 遗留问题 / 风险
- P3 首次接真实 clangd 子进程/LSP；需重点验证超时、诊断收集和 callHierarchy unsupported 路径。
- 本机 clangd 可用：`/usr/bin/clangd`，Ubuntu clangd 18.1.3。
- `docs/design_changes/change_4.md` 在 INDEX 中标记为待 P6 前决策；P3 不处理该 P4/P6 syntax-helper 策略问题。

## 下一阶段计划
- 等开发者确认 Phase 3 风险档与 restate 计划后，实现 clangd adapter。
