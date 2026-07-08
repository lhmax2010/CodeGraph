# Dev Memory 索引 (INDEX)
> 接手须知：开始任何 stage 前，先读本文件，再读所有"已 Merge"stage 的 result.md，
> 以及上一 stage 的 plan/progress/result。_archived/ 内容不读、不引用。

## 当前状态
- 当前活跃 stage：无
- 最后已确认 stage（已 Merge）：stage07_find_references
- 设计基线：docs/design.md v1.4.5 Frozen（2026-07-07；R1 change_2/change_3/change_4/change_5 已应用；change_5 已冻结，MVP background-index 下 search_symbol/get_definition 不产 not_found）
- 流程基线：docs/CodeGraph-SOP部署开发Guide.md + AGENTS.md

## stage 列表
| 编号 | 名称 | 状态 | PR 链接 | Git Commit |
|------|------|------|---------|------------|
| stage01 | metadata | 已 Merge | N/A（按用户要求只 push 不走 PR） | `2e0d0aa` / `checkpoint/phase_1_metadata` |
| stage02 | routing | 已 Merge | N/A（按用户要求只 push 不走 PR） | `b595157`（P2 代码最终提交） / `checkpoint/phase_2_routing` |
| stage03 | clangd_adapter | 已 Merge | N/A（按用户要求只 push 不走 PR） | `3bb864c`（P3 含 hardening 收口点） / `checkpoint/phase_3_clangd_adapter` |
| stage04 | treesitter | 已 Merge | N/A（按用户要求只 push 不走 PR） | `5476699`（P4 review fix 收口） / `checkpoint/phase_4_treesitter` |
| stage05 | index_build | 已 Merge | N/A（按用户要求只 push 不走 PR） | `checkpoint/phase_5_index_build`（逻辑收口 `cea43d9`） |
| stage06 | e2e | 已 Merge | N/A（按用户要求只 push 不走 PR） | `checkpoint/phase_6_e2e` |
| stage07 | find_references | 已 Merge | N/A（按用户要求只 push 不走 PR） | `checkpoint/phase_7_find_references` |

## 环境与能力预检（2026-06-13）
- Git：可用。
- Codex CLI：可用。
- Python：`python3` 可用（3.12.3）；`python` 命令不存在，开发命令需用 `python3` 或虚拟环境补 alias。
- gstack：Node/npm/Bun 不存在，gstack 按 SOP 降级为手动等价流程。
- GitHub CLI：已登录 github.com/lhmax2010，具备 repo scope。
- Remote：origin 指向 https://github.com/lhmax2010/CodeGraph.git；`main` 已包含 stage01，`phase/1-metadata` 已 push。

## 已解决的初始化资产
- `tools/cdb_rewriter.py`、`tools/verify_clangd.py` 已入库。
- `codegraph/credibility.py`、`codegraph/factories.py` 与 `tests/test_credibility.py`（旧 28 测试）已入库并通过回归。
