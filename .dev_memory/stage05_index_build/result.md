# Stage 05 - Index Build / Result

## 最终状态
待 Review。Phase 5 逻辑实现完成并已 push；完整 ARM 全量重建验收尚未执行，需在 P5 收口前由用户确认时间窗口后触发。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.21s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `108 passed in 1.42s`。
- P5 定向：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_indexing.py -q` -> `11 passed in 1.28s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `108 passed`，总覆盖率 92%，`codegraph/indexing.py` 90%。
- 静态 gate：
  - `.venv/bin/ruff check .` -> `All checks passed!`
  - `.venv/bin/black --check .` -> `20 files would be left unchanged`
  - `.venv/bin/mypy codegraph` -> `Success: no issues found in 10 source files`
  - `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过
- 补测内容：unique TU 去重、相对 `file` 按 entry `directory` 解析、missing `file` 不计入 TU、`command` 字符串解析、complete/incomplete/unknown 三态 health、缺失 clangd 降级为 `UNKNOWN/index_build_failed`、复用 `cdb_rewriter`、小型真实 clangd 建库、真实 ARM/x86 现有分片 inspect-only、CLI inspect-only、CLI `input_cdb -> rewritten CDB -> clangd background-index -> .idx -> index_health` 端到端。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Review 结果：`docs/review/phase_5_review_result.md`，三路最终 review 均无阻塞问题。
- Baseline：`d2c381b [Phase 4] docs: close treesitter stage before merge`。
- 当前分支：`phase/5-index-build`。
- 对应 Git Commit：P5 实现提交位于 `phase/5-index-build` 分支 HEAD；最终收口 commit 待 review/ARM 验收闭环后填写。

## 遗留问题 / 风险
- 已用现有真实分片验证 health 逻辑：
  - ARM `/home/linhao/Toolchain/codes/rw_arm` -> `complete shards_ge_unique_tu 3593 1303`
  - x86 `/home/linhao/Toolchain/codes/rw_x86` -> `complete shards_ge_unique_tu 1178 157`
- 完整重跑 ARM ~50s 建库需用户确认资源/时间窗口；当前实现尚未执行该验收性重跑，不能视为 P5 DoD 最终闭环。
- background-index 无逐 TU 台账，P5 只能实现保守下界判据 `shards >= unique_TU_count`，不得乐观推断项目级负证明。

## 下一阶段计划
- 等 P5 review；review 通过后，在用户确认的时间窗口重跑一次 ARM 完整建库并把真实耗时/加载数据补进本文件，再进入 merge 收口。
