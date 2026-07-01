# Stage 06 - E2E Search/Definition / Result

## 最终状态
进行中。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.99s`。
- UT 结果：待实现后填写。
- 覆盖率（行/分支）：待实现后填写。
- 补测内容：待实现后填写。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Baseline：`7717257 [Phase 5] docs: record index build checkpoint`。
- 当前分支：`phase/6-e2e-search-def`。
- 对应 Git Commit：待实现后填写。

## 遗留问题 / 风险
- 当前 `ClangdAdapter` 继承 `verify_clangd.LSPClient` 的 `--background-index=false` 默认；P6 需要显式接入 P5 全局索引能力。
- P3/P4 登记的 P6 前观察项需要在真实查询中验证：`diagnostics_wait=0.5s`、候选过度采集、宏体保守近似、真实 clangd 宏位置粒度。

## 下一阶段计划
- 等 restate 确认后开始实现 P6 API/集成层。
