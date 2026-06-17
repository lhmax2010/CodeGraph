# Stage 04 - Treesitter / Result

## 最终状态
进行中。stage 已开，等待风险档与 restate gate 确认后进入实现。

## 测试情况
- Baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.21s`。
- UT 结果：待实现后填写。
- 覆盖率（行/分支）：待实现后填写。
- 补测内容：待实现后填写。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`46ed936 [design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`。
- 当前分支：`phase/4-treesitter`。
- 对应 Git Commit：待实现后填写。

## 遗留问题 / 风险
- 当前裸 `python3` 未安装 tree-sitter binding；通过 `uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4` 可运行真实 tree-sitter。P4 实现前需确认依赖运行口径。
- P4 开发/测试运行口径已确认：使用项目本地 `.venv`，其中 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4` 可直接 import；现有 90 测试已在该 venv 通过。
- P4 需回改已 Merge 的 P2 `_has_preprocessor_blind_spot()`，仅允许删除 `symbol_kind==MACRO` 短路，不得改 QR1-9/状态机/降级真值表。

## 下一阶段计划
- 等开发者确认高风险档与 restate 计划后实现 Phase 4。
