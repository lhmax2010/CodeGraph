# Stage 03 - Clangd Adapter / Result

## 最终状态
已 Merge。P3 review 修复核查通过；按用户指令，本项目只 `git push`，不创建 PR。

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
- P3 代码最终提交：`89b0e3d [Phase 3] fix: clean up clangd subprocess on init failure + add P2 seam test`，并追加 hardening 收尾提交 `[Phase 3] harden: BaseException cleanup on init + reap killed clangd`。
- Checkpoint：`checkpoint/phase_3_clangd_adapter`。

## 遗留问题 / 风险
- P3 已用小型 CDB 跑通本机 clangd 18.1.3 的 definition/references/callHierarchy；GBS/ARM 真机与大索引验证仍按设计留给 P5/P7。
- 本机 clangd 可用：`/usr/bin/clangd`，Ubuntu clangd 18.1.3。
- `docs/design_changes/change_4.md` 在 INDEX 中标记为待 P6 前决策；P3 不处理该 P4/P6 syntax-helper 策略问题。
- P3 只产 observation，不做 P2 路由可信度、不做 P4 tree-sitter、不做 P5 index_health。

## P6/P8 前待验证 / 待解决
- [P6 前·重要] `diagnostics_wait=0.5s` 在大型 Tizen TU 上可能不够：clangd 异步发布诊断，大 TU 解析超过 0.5s 时，P3 可能漏报 include-not-found，导致 P2 误判依赖完整、保留本该降级的 must 结果（虚假可信风险）。P6 真机必须验证 `diagnostics_wait` 是否足够，可能要改成“轮询到诊断稳定”，并加真实 missing-include 大 TU 回归测试。
- [P8 前] `prepareCallHierarchy` 返回空时，“符号定位不到”和“符号有但零调用者”不可区分；P8 做 `find_callers` 时可能把前者误判为 not_found（虚假否定）。P8 前需让 P3/协议能表达“符号已定位”。
- [P6/P8 前] 多 location 一律判 `symbol_ambiguous`，合法 C++ 重载会被降级。P3 作为 observation 层不应判“是否合法重载”；后续可能要 P3 只报 location 数量，由 P2/P6 结合上下文判定。
- [NIT] `kind_filter` 期望 `SymbolKind` value（非 API 简化名）；include-not-found / unsupported 目前用字符串启发式判断，跨 clangd 版本需真机复验。

## 下一阶段计划
- 进入后续 Phase；P6 前必须先处理 `change_4.md` 和本文件登记的 P6 前待验证项。
