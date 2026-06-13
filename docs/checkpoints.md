# Checkpoints

> 记录通过 stage gate 的可信提交或 tag。destructive rollback 前必须按 AGENTS.md 规则确认工作区状态并取得授权。

| Phase | Checkpoint | Commit | 覆盖范围 | 回退后状态 |
|-------|------------|--------|----------|------------|
| Phase 1 | `checkpoint/phase_1_metadata` | `2e0d0aa3e6274c290e1dfa6570e78fa98a40b3fe` | 元数据层、§4.1 类型、engine protocol、INV1-16/18-21、复用资产入库 | stage01_metadata 已 Merge；Phase 2 未启动 |
