# Stage 05 - Index Build / Result

## 最终状态
进行中。stage 已开，等待风险档、环境探测报告与 restate gate 确认后进入实现。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.21s`。
- UT 结果：待实现后填写。
- 覆盖率（行/分支）：待实现后填写。
- 补测内容：待实现后填写。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`d2c381b [Phase 4] docs: close treesitter stage before merge`。
- 当前分支：`phase/5-index-build`。
- 对应 Git Commit：待实现后填写。

## 遗留问题 / 风险
- P5 可复用真实 ARM/x86 CDB 与现有 background-index 分片；完整重跑 ARM ~50s 建库需用户确认资源/时间窗口。
- background-index 无逐 TU 台账，P5 只能实现保守下界判据 `shards >= unique_TU_count`，不得乐观推断项目级负证明。

## 下一阶段计划
- 等开发者确认高风险档、环境探测报告与 restate 计划后实现 Phase 5。
