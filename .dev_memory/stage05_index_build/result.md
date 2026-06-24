# Stage 05 - Index Build / Result

## 最终状态
待 Merge。Phase 5 逻辑实现、review 修复、三路最终 review 与 ARM 真机完整建库验收均已完成。

## 测试情况
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `97 passed in 0.21s`。
- UT 结果：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `113 passed in 1.51s`。
- P5 定向：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_indexing.py -q` -> `16 passed in 1.32s`。
- 覆盖率（行/分支）：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `113 passed`，总覆盖率 92%，`codegraph/indexing.py` 91%。
- 静态 gate：
  - `.venv/bin/ruff check .` -> `All checks passed!`
  - `.venv/bin/black --check .` -> `20 files would be left unchanged`
  - `.venv/bin/mypy codegraph` -> `Success: no issues found in 10 source files`
  - `.venv/bin/python -m compileall -q codegraph tools tests` -> 通过
- 补测内容：unique TU 去重、相对 `file` 按 entry `directory` 解析、missing `file` 不计入 TU、`command` 字符串解析、complete/incomplete/unknown 三态 health、空 CDB `no_translation_units`、缺失 clangd 降级为 `UNKNOWN/index_build_failed`、复用 `cdb_rewriter`、库形态下自动加载 `tools/cdb_rewriter.py`、CLI 非法输入结构化 JSON、小型真实 clangd 建库、真实 ARM/x86 现有分片 inspect-only、CLI inspect-only、CLI `input_cdb -> rewritten CDB -> clangd background-index -> .idx -> index_health` 端到端。

## 真机验收
- ARM 完整建库输入：`/home/linhao/Toolchain/codes/rw_arm/compile_commands.json`
- ARM buildroot：`/home/linhao/GBS-ROOT-TOOLCHAIN-GCC-PATCHES2/local/BUILD-ROOTS/scratch.armv7l.0`
- 临时输出目录：`/tmp/codegraph-p5-arm-index-20260624-154443`
- 命令：`PYTHONPATH=.:tools .venv/bin/python tools/build_index.py --input-cdb /home/linhao/Toolchain/codes/rw_arm/compile_commands.json --output-dir /tmp/codegraph-p5-arm-index-20260624-154443 --buildroot /home/linhao/GBS-ROOT-TOOLCHAIN-GCC-PATCHES2/local/BUILD-ROOTS/scratch.armv7l.0 --jobs 8 --max-wait 180 --poll-interval 1 --stable-rounds 3`
- 建库结果：exit code 0；wall time 31.701s；`build.elapsed_seconds=31.405s`；`stable=True`；clangd exit code 0。
- 分片结果：3593 `.idx` / 47M；`unique_tu_count=1303`；`index_health=complete`，reason=`shards_ge_unique_tu`。
- 加载/复用耗时：`PYTHONPATH=.:tools .venv/bin/python tools/build_index.py --compile-commands-dir /tmp/codegraph-p5-arm-index-20260624-154443 --jobs 8 --max-wait 60 --poll-interval 0.2 --stable-rounds 2` -> wall time 1.345s，`load.elapsed_seconds=1.221s`，3593 `.idx`，`index_health=complete`。
- DoD 结论：从真实 ARM CDB 到 rewritten CDB 再到 clangd background-index 分片的完整流程已在临时目录复现；未覆盖现有 `/home/linhao/Toolchain/codes/rw_arm/.cache` 分片。
- P7 留底（非 P5 gate）：`verify_clangd.py` 对 `gstelement.c` 中 `gst_element_set_state` 可完成 definition/references 语义探测，返回 references=2；未复现可行性报告中的 389 refs/62 files，留给 P7 继续核查。

## PR 与代码
- PR 链接：N/A（按用户要求只 push，不创建 PR）。
- Review 结果：`docs/review/phase_5_review_result.md`，三路最终 review 均无阻塞问题。
- Baseline：`d2c381b [Phase 4] docs: close treesitter stage before merge`。
- 当前分支：`phase/5-index-build`。
- 对应 Git Commit：ARM 验收记录在 `phase/5-index-build` HEAD；P5 逻辑收口为 `6aa3462 [Phase 5] fix: harden index CLI input and cdb rewriter import`。

## 遗留问题 / 风险
- 已用现有真实分片验证 health 逻辑：
  - ARM `/home/linhao/Toolchain/codes/rw_arm` -> `complete shards_ge_unique_tu 3593 1303`
  - x86 `/home/linhao/Toolchain/codes/rw_x86` -> `complete shards_ge_unique_tu 1178 157`
- background-index 无逐 TU 台账，P5 只能实现保守下界判据 `shards >= unique_TU_count`，不得乐观推断项目级负证明。
- Review NIT（不阻塞）：CLI 目前未额外捕获 `PermissionError`；`_load_cdb_rewriter()` 会 mutate 全局 `sys.path`，属于标准 bootstrap，可接受；该修复假设 `tools/` 与 `codegraph/` 在源码树中相邻，pip 打包形态可能需要额外 packaging 规则，与当前部署模型一致。

## 下一阶段计划
- 等用户核对 DoD 后 merge `phase/5-index-build` 到 `main`，打 `checkpoint/phase_5_index_build`，再开 Phase 6。
