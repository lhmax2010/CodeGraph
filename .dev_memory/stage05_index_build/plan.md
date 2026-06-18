# Stage 05 - Index Build / Plan

## 目标
启动 CodeGraph Phase 5：离线建库 + `index_health`。按 `docs/design.md` v1.4.4 §7 Phase 5 落地：
- 固化 `compile_commands.json` 改写后喂给 clangd background-index 的建库流程。
- 按 build config 隔离目录（如 `rw_arm/`、`rw_x86/`）产出/复用 `.cache/clangd/index/*.idx`。
- 实现完成判定：clangd 退出码 0 + index 分片稳定。
- 实现覆盖率粗判下界：`idx_shards >= unique_TU_count` 才可标 `complete`，否则 `incomplete`。
- 实现 `.idx` 扩展名防御回退和 `index_health` 真值表产出。

## 范围边界
做：
- 新增 P5 indexing 模块/脚本，复用 `tools/cdb_rewriter.py`，不重写 CDB 改写逻辑。
- 对 CDB 做输入统计：entry 数、unique TU 数、existing file 数、target/sysroot/config 摘要。
- 调用 clangd background-index 建库，监测 `.cache/clangd/index` 分片数量和稳定性。
- 产出结构化 `index_health`：`complete` / `incomplete` / `unknown`，以及 shards 数、TU 数、原因 notes。
- 支持按 config 隔离：`rw_arm`、`rw_x86` 或调用方传入的任意 config 输出目录。
- 小型工程集成测试 + 已有 ARM/x86 CDB 探测路径；如确认允许，复用真实 `/home/linhao/Toolchain/codes/rw_arm` 与 `rw_x86` 做真机验证。

不做：
- 不做 not_found 级别判定；P5 只产出 `index_health` 事实，P2 据此决定能不能 not_found。
- 不实现增量索引、逐 TU 台账、staleness 检测、clangd-indexer、单一只读 `.idx` 分发（二期）。
- 不修改 §4 接口/INV/QR 契约，不改 P2 路由状态机。
- 不把 coverage 粗判写成 ratio 阈值；禁止 `ratio >= 0.95` 之类乐观判据。

## 计划步骤
1. 复核 `tools/cdb_rewriter.py` API/CLI，确定 P5 只调用现有 rewrite 能力，不复制实现。
2. 设计 `codegraph/indexing.py` 的最小 dataclass：CDB 统计、index build config、index build result、index health summary。
3. 实现 CDB 读取/统计：entry 数、unique TU 数、文件存在性、target/sysroot/build_config 摘要。
4. 实现 index 分片扫描：优先 `.idx`，若没有 `.idx` 则列出目录实际文件扩展名并标 `unknown` 或 defensive fallback。
5. 实现 health 真值表：
   - index 目录不存在/异常/clangd 失败/分片未稳定 -> `unknown`
   - 分片数 `< unique_TU_count` -> `incomplete`
   - 分片数 `>= unique_TU_count` -> `complete`
6. 实现 background-index runner：启动 clangd `--background-index=true --compile-commands-dir=<dir>`，打开一个或多个 TU 触发索引，等待分片数稳定并收集耗时/退出码。
7. 写测试：纯函数单测覆盖 complete/incomplete/unknown、`.idx` 扩展名防御、CDB 统计；小型临时 C 工程真实 clangd smoke 产出 `.idx`。
8. 若用户确认允许真机验证，跑已有 `rw_arm` / `rw_x86` 的健康检测与必要的轻量复用验证；是否重跑完整 50s 建库需确认资源/时间。
9. 跑 gate：`.venv` pytest、ruff、black、mypy、coverage、compileall；结果写入 progress。

## 依赖前置阶段
- 已完成并 Merge：stage01_metadata、stage02_routing、stage03_clangd_adapter、stage04_treesitter。
- P5 独立于 P6；它只给 P2/P6 提供 `index_health` 输入事实。

## Baseline（改前状态）
- Git baseline：`d2c381b` (`[Phase 4] docs: close treesitter stage before merge`)。
- 分支：从 `main@d2c381b` 新建 `phase/5-index-build`。
- Baseline 测试命令：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q`
- Baseline 测试结果：`97 passed in 0.21s`。

## 环境探测报告
1. `cdb_rewriter.py` 复用资产：
   - 路径：`tools/cdb_rewriter.py`。
   - `PYTHONPATH=.:tools python3 -c "import cdb_rewriter"` 成功。
   - `python3 tools/cdb_rewriter.py --help` 可运行，CLI 支持 `--buildroot`、`--target`、`--resource-dir`、`--keep-missing-files`。
2. GBS/CDB：
   - `gbs` 可用：`gbs 2.0.6`。
   - 真实 CDB 已存在：
     - `/home/linhao/Toolchain/codes/rw_x86/compile_commands.json`：207 entries，157 unique TU，target `x86_64-tizen-linux-gnu`，sysroot `/home/linhao/GBS-ROOT-TIZEN-LLVM/local/BUILD-ROOTS/scratch.x86_64.0`。
     - `/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`：1304 entries，1303 unique TU，target `armv7l-tizen-linux-gnueabi`，sysroot `/home/linhao/GBS-ROOT-TOOLCHAIN-GCC-PATCHES2/local/BUILD-ROOTS/scratch.armv7l.0`。
   - CDB 形状：entries 使用 `arguments` 数组，前几项包含 driver、`--sysroot=...`、`--target=...`、`--no-default-config`、include/define flags；文件路径均已存在。
   - GBS ARM 构建日志存在：`/home/linhao/Toolchain/codes/gbs-build-gstreamer-armv7l.log`，显示 2026-06-09 用 `gbs 2.0.6` 成功构建 gstreamer armv7l，buildroot 位于 `scratch.armv7l.0`。
3. clangd background-index：
   - `clangd` 可用：Ubuntu clangd 18.1.3。
   - 当前环境小型工程 smoke 已实跑：临时 C 工程启动 `clangd --background-index=true --compile-commands-dir=<tmp> -j=2` 后产出 `.cache/clangd/index/main.c....idx`。
   - 真实已建索引存在：
     - `rw_arm/.cache/clangd/index`：3593 `.idx`，47M；按 `3593 >= 1303 unique TU` 下界判据为 complete。
     - `rw_x86/.cache/clangd/index`：1178 `.idx`，9.5M；按 `1178 >= 157 unique TU` 下界判据为 complete。
4. ARM/Tizen 真机验证可用性：
   - 当前机器有 ARM/Tizen GBS 产物、ARM CDB、ARM clangd background-index 分片和既有探测报告，不是只有 x86。
   - `/home/linhao/Toolchain/codes/global-index-feasibility-report.md` 记录 ARM 1303 TU 首建约 50s、47MB/3593 分片、运行时加载 ≤10s、find_references 从 2/1 扩到 389/62。
   - 本次开 stage 只做探测与复用确认，未重跑完整 50s 建库；P5 实现后可按用户确认复跑或复用现有 ARM/x86 索引做验收。

## 风险档判断
Phase 5 风险档候选：高。

理由：
- P5 第一次把 CodeGraph 接到真实 GBS/ARM 与 clangd background-index 产物，涉及外部 buildroot、CDB、子进程耗时、磁盘分片稳定性。
- `index_health` 会影响 P2/P6 对 not_found 的上游输入；虽然 P5 不判 not_found，但误报 complete 会扩大虚假否定风险。
- background-index 没有逐 TU 台账，只能用保守下界判据；实现必须宁可低估完整性，不可乐观。
- 环境已有 ARM/x86 真实数据可验，但完整重建有资源/时间成本，需在实现前确认真机验收跑法。

## 当前暂停点
stage05 已开，等待风险档、环境报告与 restate gate 确认后再实现。
