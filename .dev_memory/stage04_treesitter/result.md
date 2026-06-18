# Stage 04 - Treesitter / Result

## 最终状态
已 Merge。P4 修复确认三路通过，按用户指令 fast-forward merge 到 main；本项目只 `git push`，不创建 PR。

## 测试情况
- Baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.21s`。
- P2 回归：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_phase2_routing.py -q` -> `14 passed in 0.15s`。
- P4 专项：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_treesitter_adapter.py -q` -> `6 passed in 0.03s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.19s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `97 passed in 0.34s`，total 93%，`codegraph/engines/treesitter_adapter.py` 83%。
- 确定性检查：
  - `.venv/bin/python -m compileall -q codegraph tools tests`：通过，无输出。
  - `.venv/bin/ruff check .`：All checks passed。
  - `.venv/bin/black --check .`：17 files would be left unchanged。
  - `.venv/bin/mypy codegraph`：Success, no issues in 9 source files。
- 补测内容：新增 `tests/test_treesitter_adapter.py`，覆盖 tree-sitter binding 不可得降级、真实 C parser 候选抽取、search/candidates_near 评分、候选 not_evidence/syntactic 标注、`#define` 宏定义位置非伪位置可 OK、宏体位置盲区降级、无法解析文件保守降级、无 helper 仍保守降级；更新 `tests/test_phase2_routing.py` 覆盖宏定义在 helper 判定为真实源码时可保留 semantic OK。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`46ed936 [design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`。
- 当前分支：`phase/4-treesitter`。
- P4 代码与 review fix 收口提交：`5476699 [Phase 4] fix: conservative blind-spot when file unparsable + drop dead param`。
- Checkpoint：`checkpoint/phase_4_treesitter`。

## 遗留问题 / 风险
- 当前裸 `python3` 未安装 tree-sitter binding；通过 `uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4` 可运行真实 tree-sitter。P4 实现前需确认依赖运行口径。
- P4 开发/测试运行口径已确认：使用项目本地 `.venv`，其中 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4` 可直接 import；现有 90 测试已在该 venv 通过。
- P4 已回改已 Merge 的 P2 `_has_preprocessor_blind_spot()`：仅删除 `symbol_kind==MACRO` 短路，保留 `syntactic_provider is None -> True`，P2 回归测试已通过。

## 后续待处理
- [P6前] 候选符号过度采集：`_symbols_from_declaration()` 当前会把初始化表达式里的 identifier 也采成候选，可能产生幻影/错类候选；P6 真实代码前收紧到只采声明的标识符。
- [P6前] 宏体内保守近似：当前宏体所有位置判伪位置。
- [P6前·新] 真机验证 clangd 实际返回的宏相关位置，确认 helper 的位置判定在真实 Tizen 代码上够用（diagnostics/位置粒度）。

## 下一阶段计划
- 进入 Phase 5：离线建库 + index_health。
