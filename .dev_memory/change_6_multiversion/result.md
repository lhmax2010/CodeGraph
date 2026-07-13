# Change 6 - Multiversion clangd Support / Result

## 最终状态
- design v1.5.0 已冻结：`design/v1.5.0` 指向 change_6 冻结点 `bb1e7ee`。
- main 已记录设计基线为 `docs/design.md v1.5.0 Frozen`。

## 验证记录
- 三版本 spot-check 原始记录：`.dev_memory/change_6_multiversion/spotcheck-20260710.txt`

## 结转 NIT
- 术语一致性：`runtime probe` 术语在 `docs/design.md` 的三处摘要（约 line 22/843/1025）未同步为"反应式判定"；可在 change_6 实现期一并清理。
- 审计日志补强：3593 -> 3614 污染实证（clangd 21 接触 clangd 18 cache 导致 shards 变化）已写入 design 正文，但尚未进入 spot-check 日志；实现期补充观测命令与前后计数到归档。
