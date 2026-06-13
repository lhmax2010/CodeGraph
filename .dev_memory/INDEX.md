# Dev Memory 索引 (INDEX)
> 接手须知：开始任何 stage 前，先读本文件，再读所有"已 Merge"stage 的 result.md，
> 以及上一 stage 的 plan/progress/result。_archived/ 内容不读、不引用。

## 当前状态
- 当前活跃 stage：stage01_metadata（准备中；编码因复用资产缺失暂停）
- 最后已确认 stage（已 Merge）：无
- 设计基线：docs/design.md v1.3 Frozen（2026-06-11）
- 流程基线：docs/CodeGraph-SOP部署开发Guide.md + AGENTS.md

## stage 列表
| 编号 | 名称 | 状态 | PR 链接 | Git Commit |
|------|------|------|---------|------------|
| stage01 | metadata | 准备中 | - | baseline 804d50c |

## 环境与能力预检（2026-06-13）
- Git：可用。
- Codex CLI：可用。
- Python：`python3` 可用（3.12.3）；`python` 命令不存在，开发命令需用 `python3` 或虚拟环境补 alias。
- gstack：Node/npm/Bun 不存在，gstack 按 SOP 降级为手动等价流程。
- GitHub CLI：已登录 github.com/lhmax2010，具备 repo scope。
- Remote：origin 指向 https://github.com/lhmax2010/CodeGraph.git；远端当前无 heads。

## 初始化阻塞 / 待补资产
- `tools/cdb_rewriter.py` 未在当前仓库发现，后续 P3/P5 前需补入或确认来源。
- `tools/verify_clangd.py` 未在当前仓库发现，后续 P3 前需补入或确认来源。
- 既有 `codegraph/credibility.py`、`codegraph/factories.py` 与 `tests/test_credibility.py`（28 测试）未在当前仓库发现；P1 编码前必须处理。
