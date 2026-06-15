# Stage 03 - Clangd Adapter / Result

## 最终状态
待 Review（实现完成；三路 review 待跑，尚未 Merge）。

## 测试情况
- Baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `80 passed in 0.07s`。
- P3 单测：`PYTHONPATH=.:tools python3 -m pytest tests/test_clangd_adapter.py -q` -> `10 passed in 0.14s`。
- UT 结果：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `90 passed in 0.18s`。
- 覆盖率：`PYTHONPATH=.:tools uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `90 passed in 0.40s`，total 97%，`codegraph/engines/clangd_adapter.py` 100%。
- 确定性检查：
  - `python3 -m compileall -q codegraph tools tests`：通过，无输出。
  - `uv tool run ruff check .`：All checks passed。
  - `uv tool run black --check .`：15 files would be left unchanged。
  - `uv tool run mypy codegraph`：Success, no issues in 8 source files。
- 补测内容：新增 `tests/test_clangd_adapter.py`，覆盖 fake LSP 转换、P2 observation 接缝、空 definition 不判 not_found、diagnostics 分类、workspace symbol、references limit/offset、callHierarchy incoming/outgoing 方向、unsupported/timeout/error 传播、init 失败清理已启动 client、P3 observation 进入 P2 后按 include-not-found 降级、malformed LSP shape 容错，以及真实 clangd 小 CDB 的 definition/references/callHierarchy 集成。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`e87543d [Phase 2] docs: close routing stage`。
- 当前分支：`phase/3-clangd-adapter`。
- 对应 Git Commit：分支 HEAD 的 Phase 3 review fix 提交（具体 hash 见 `git log`）。

## 遗留问题 / 风险
- P3 已用小型 CDB 跑通本机 clangd 18.1.3 的 definition/references/callHierarchy；GBS/ARM 真机与大索引验证仍按设计留给 P5/P7。
- 本机 clangd 可用：`/usr/bin/clangd`，Ubuntu clangd 18.1.3。
- `docs/design_changes/change_4.md` 在 INDEX 中标记为待 P6 前决策；P3 不处理该 P4/P6 syntax-helper 策略问题。
- P3 只产 observation，不做 P2 路由可信度、不做 P4 tree-sitter、不做 P5 index_health。

## 下一阶段计划
- 生成 Phase 3 review prompt，跑三路 AI review，按 R14 闭环后再考虑 merge。
