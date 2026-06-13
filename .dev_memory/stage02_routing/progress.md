# Stage 02 - Routing / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 2 开 stage baseline 取 `main@9e1157f`，从该提交新建 `phase/2-routing`。
  - 原因：stage01_metadata 已 Merge，`main` 干净且 P1 baseline 67 tests 全过。
  - 排除的方案：从旧 `phase/1-metadata` 继续开发。该方案会绕开已 Merge 的 main 收尾状态。
- 决策：Phase 2 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P2 同时承载路由状态机、降级真值表、四道护栏触发和 QR1-9 容器校验，组合面明显大于 P1；但仍可用协议桩隔离验证。
  - 排除的方案：简单按设计 §7 预估规模归为普通风险。该方案低估了 QR/路由交叉错误对后续阶段的扩散风险。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage02_routing` 为当前活跃 stage，记录 baseline commit。
- 文件/模块：`.dev_memory/stage02_routing/plan.md`
  - 改动内容：记录 Phase 2 目标、范围边界、计划步骤、baseline 与风险档候选。
- 文件/模块：`.dev_memory/stage02_routing/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage02_routing/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 2 收尾时填写。

## 进度日志
- [2026-06-13] 读取 `docs/design.md` v1.4.2 与 `.dev_memory/INDEX.md`，确认 stage01 已 Merge、Phase 2 未启动。
- [2026-06-13] 在 `main@9e1157f` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q`，结果 `67 passed in 0.07s`。
- [2026-06-13] 从 `main@9e1157f` 新建分支 `phase/2-routing`。
- [2026-06-13] 创建 `.dev_memory/stage02_routing/` 计划与进度骨架；等待 restate gate 确认后再实现。
