# CodeGraph 团队验证指南 / 自检记录

## 状态
- 指南基线：`main@5506c9b`，design v1.5.0，MVP 九层闭环。
- 自检环境：普通用户（uid 1000），Linux 6.17.0 x86_64，20 CPU，Python 3.12.3，
  系统 clangd 18.1.3；另用 clangd 21.1.1 做错版本守卫抽查。
- 归档指南：`docs/verification_guide.md`。
- 生产隔离：全部建库、查询、损坏与 SIGKILL 实验只使用 `/tmp/codegraph-guide-selfcheck-20260720`；
  未读取、修改或重建 rw_arm 生产 cache。

## Mini 工程
- 源码：`api.h`、`core.c`、`worker.c`、`main.c`。
- `core.c` 定义 `compute_value()`；`worker.c` 调用两次；`main.c` 调用一次，形成跨 TU 查询样本。
- CDB：3 个标准 `arguments` 形态 entry，均先用 `/usr/bin/cc -std=c11` 实际编译并链接运行。
- 建库结果：3 unique TU、4 `.idx`（含 header shard），约 3.1s，health complete；stamp 为
  `clangd 18.1.3`。重复完整建库仍 complete，dirty marker 不残留。

## 第一轮（原 v1.0）
### 通过项
- L1：连续五轮均 `365 passed`，耗时 5.08-5.22s，无时序抖动。
- L2：首次建库与幂等重跑均 complete。
- L4：stdio 空闲时 stdout/stderr 均为 0 bytes；五工具完整；unknown/build_config_id/missing
  三类攻击均为结构化 `invalid_params`。
- L5 A-D：错版本 mismatch 且 shards 不变；无 stamp 降 unknown/current_tu；损坏 stamp 阻断；
  SIGKILL 后 dirty 优先、绝不假 complete，同版本可接管恢复。

### 发现并交 PM 修订
1. L3 示例访问不存在的 `Result.file/pos`，应打印 `Result.data`。
2. definition 应从调用点查询，不能把定义位置同时当 query position。
3. Ubuntu/Debian 缺 `python3-venv` 时 `python3 -m venv` 不可执行，需明确前置包。
4. 无 stamp 的非空 cache 不能直接重跑 builder 自动认领；需显式追认或换空目录从零建。
5. L2 JSON 路径应为 `build.health_report.health`；stamp 在 `index/`，lock 在父级 `clangd/`。
6. L5 B/C 备份需项目隔离与恢复保护；D/E 需给可复制命令。
7. §1 补充易误报行为：tree-sitter 不可用降级、非 call graph 的 engine_version=None、callers
   版本差异、完整重建 mtime、verified 同版本刷新、SIGKILL/断电边界等。

## 第二轮（PM 修订版）
- L3 原样脚本仅替换六个变量后完整通过：
  - search：OK/complete，1 semantic，命中 `core.c`。
  - definition：从 `worker.c` 调用点命中 `core.c` 定义，OK/complete。
  - references：OK/complete，`4 semantic + 1 not_evidence candidate = 5`。
  - callers：OK/complete，3 条真实调用，`engine_version=clangd 18.1.3`。
  - callees：clangd 18 如实 FAILED + callhierarchy_unsupported。
  - 不存在符号：UNRESOLVED/unknown，未产 not_found。
  - `s.data` sample 正常打印；semantic source/certainty、candidate warning、exhaustive=False 均符合契约。
- §2：`python3-venv` 包名在本机 apt 元数据中存在，修订后的 Ubuntu/Debian 前置命令准确。
- L2：修订后的 JSON 键和 lock/stamp 路径与真机输出一致。
- L5 B/C：新备份路径与恢复命令可执行，状态恢复为 committed clangd 18 cache。
- L5 D：按修订命令 SIGKILL；dirty 存在，inspect 为
  `unknown/index_engine_build_in_progress`（exit 1）；同版本重跑恢复 complete 并清 dirty。
- L5 E：并发双 builder 一个 complete、另一个 `index_engine_build_in_progress`，无双写。
- 抽查回归：L1 单轮 `365 passed`；L2 inspect complete；L4 五工具 schema + unknown 参数攻击通过。
- §1 新增表述与 design v1.5.0/change_6 的实现边界一致。

## 结论
- PM 修订版指南在本机普通用户环境可执行，第一轮七项问题均已修复并复验通过。
- 团队可从 `docs/verification_guide.md` 开始异构环境验证；团队结果尚待收集。
