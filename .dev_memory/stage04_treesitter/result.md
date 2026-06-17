# Stage 04 - Treesitter / Result

## 最终状态
待 Review。P4 实现已完成，等待多路 review 与人工核查；按用户指令，本项目只 `git push`，不创建 PR。

## 测试情况
- Baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.21s`。
- P2 回归：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `14 passed in 0.15s`。
- P4 专项：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_treesitter_adapter.py -q` -> `5 passed in 0.02s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `96 passed in 0.19s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `96 passed in 0.33s`，total 92%，`codegraph/engines/treesitter_adapter.py` 82%。
- 确定性检查：
  - `.venv/bin/python -m compileall -q codegraph tools tests`：通过，无输出。
  - `.venv/bin/ruff check .`：All checks passed。
  - `.venv/bin/black --check .`：17 files would be left unchanged。
  - `.venv/bin/mypy codegraph`：Success, no issues in 9 source files。
- 补测内容：新增 `tests/test_treesitter_adapter.py`，覆盖 tree-sitter binding 不可得降级、真实 C parser 候选抽取、search/candidates_near 评分、候选 not_evidence/syntactic 标注、`#define` 宏定义位置非伪位置可 OK、宏体位置盲区降级、无 helper 仍保守降级；更新 `tests/test_phase2_routing.py` 覆盖宏定义在 helper 判定为真实源码时可保留 semantic OK。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`46ed936 [design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`。
- 当前分支：`phase/4-treesitter`。
- 对应 Git Commit：待提交后填写。

## 遗留问题 / 风险
- 当前裸 `python3` 未安装 tree-sitter binding；通过 `uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4` 可运行真实 tree-sitter。P4 实现前需确认依赖运行口径。
- P4 开发/测试运行口径已确认：使用项目本地 `.venv`，其中 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4` 可直接 import；现有 90 测试已在该 venv 通过。
- P4 已回改已 Merge 的 P2 `_has_preprocessor_blind_spot()`：仅删除 `symbol_kind==MACRO` 短路，保留 `syntactic_provider is None -> True`，P2 回归测试已通过。

## 下一阶段计划
- 进入 Phase 4 review；review 通过后再按收尾流程 merge/tag/checkpoint。
