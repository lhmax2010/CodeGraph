# Stage 01 - Metadata / Result

## 最终状态
实现完成，待 Review。按用户指令，本项目只 `git push`，不创建 PR。

## 测试情况
- UT 结果：
  - `PYTHONPATH=.:tools python3 -m pytest tests/ -q`：59 passed in 0.05s。
  - `PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q`：28 passed in 0.02s。
  - `python3 -m compileall -q codegraph tools tests`：通过，无输出。
- 覆盖率（行/分支）：未生成；`pytest-cov` 未安装，`--cov` 参数不可用。
- 未运行成功的确定性检查：
  - `ruff check`：`ruff` 命令不存在。
  - `black --check .`：`black` 命令不存在。
  - `mypy codegraph`：`mypy` 命令不存在。
- 补测内容：新增 `tests/test_phase1_metadata.py`，覆盖 INV13-16/18/19、预留值、`make_error_credibility()`、`QueryMeta` frozen dataclass、`QueryResult`/`Candidate` 默认值、Engine/Syntactic 协议导出。

## PR 与代码
- PR 链接：N/A（用户明确要求不走 PR，只 push）。
- 对应 Git Commit：本次 Phase 1 feat 提交（见 git log）

## 遗留问题 / 风险
- 开发工具缺失：`ruff`、`black`、`mypy`、`pytest-cov` 未安装；本次无法完成 lint/type/coverage gate。
- P1 只定义协议形状，不实现 P2 QR1-9、路由状态机、P3/P4 引擎适配、P5 建库、P6+ API。
- `tools/verify_clangd.py` 与 `tools/cdb_rewriter.py` 已作为复用资产入库，但未在 P1 中改动逻辑。

## 下一阶段计划
Review 通过后，进入 Phase 2：路由判定核心 + QR1-9 容器校验。Phase 2 不得实现 P4 评分算法本身，只读取候选 relevance_score。
