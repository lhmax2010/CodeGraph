# Stage 06 - E2E Search/Definition / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：P6 风险档定为高风险。
  - 原因：这是 P1-P5 首次真实集成，主要风险来自 clangd/P5 索引、P4 helper、P2 路由契约之间的接缝。
  - 排除的方案：不把 P6 当作单模块实现阶段处理。
- 决策：P6 先接链路跑真实查询，再针对性处理 P6 前遗留项。
  - 原因：P6 的核心价值是暴露集成问题；预防性返工 P3/P4 容易扩大范围并掩盖真实接缝。
  - 排除的方案：开工前逐个预防性修完 `diagnostics_wait`、候选过度采集、宏体近似。
- 决策：P6 必须显式处理 clangd background-index 模式。
  - 原因：当前 `ClangdAdapter` 复用的 `LSPClient` 默认带 `--background-index=false`，与 P5 result 里 2 refs vs 389 refs 的证据一致；真实跨文件查询需要消费 P5 全局索引。
  - 排除的方案：沿用单 TU 模式冒充端到端。

## 改动摘要
- 文件/模块：
  - `.dev_memory/INDEX.md`：登记 stage06 进行中。
  - `.dev_memory/stage05_index_build/result.md`：校正 stage05 已 Merge 事实。
  - `.dev_memory/stage06_e2e/plan.md`：记录 P6 计划、边界、集成问题。

## 进度日志
- 2026-07-01 从 `main` 开 `phase/6-e2e-search-def`，baseline `7717257 [Phase 5] docs: record index build checkpoint`。
- 2026-07-01 baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.99s`。
- 2026-07-01 探测：`/home/linhao/Toolchain/codes/rw_arm/.cache/clangd/index` 存在 3593 个 `.idx`；P5 验收临时 `/tmp/codegraph-p5-arm-index-20260624-154443` 已不可用，P6 可复用现有真实分片。
