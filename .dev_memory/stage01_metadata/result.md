# Stage 01 - Metadata / Result

## 最终状态
已 Merge。按用户指令，本项目只 `git push`，不创建 PR；Phase 2 尚未启动。

## 测试情况
- UT 结果：
  - `PYTHONPATH=.:tools python3 -m pytest tests/ -q`：67 passed in 0.05s。
  - `PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q`：28 passed in 0.02s。
  - `python3 -m compileall -q codegraph tools tests`：通过，无输出。
- 确定性检查：
  - `/home/linhao/.local/bin/uv tool run ruff check .`：All checks passed。
  - `/home/linhao/.local/bin/uv tool run black --check .`：11 files would be left unchanged。
  - `/home/linhao/.local/bin/uv tool run mypy codegraph`：Success, no issues in 6 source files。
- 覆盖率（P1 核心范围）：
  - `PYTHONPATH=.:tools /home/linhao/.local/bin/uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing`：67 passed；`codegraph` total coverage 97%。
  - 全仓库 `--cov=codegraph --cov=tools` 已能运行且测试通过，但 total coverage 为 58%，原因是 `tools/verify_clangd.py` 是外部 clangd/LSP 集成资产，P1 不在本地覆盖该真机/子进程路径；此项作为 coverage 例外记录。
- 补测内容：新增 `tests/test_phase1_metadata.py`，覆盖 INV13-16/18-21、预留值、`make_error_credibility()`、`QueryMeta` frozen dataclass、`QueryResult`/`Candidate` 默认值、Engine/Syntactic 协议导出、§2.1 future annotations 守护、`consumer_hint` hash/equality、合法 `log_search+syntactic`、`validate()` identity、协议 stub、enum/string 边界。

## PR 与代码
- PR 链接：N/A（用户明确要求不走 PR，只 push）。
- 对应 Git Commit：`2e0d0aa [Phase 1] fix: implement INV20 and INV21`。
- Merge 方式：`main` fast-forward merge `phase/1-metadata`，已 push 到 `origin/main`。
- Checkpoint：`checkpoint/phase_1_metadata` -> `2e0d0aa3e6274c290e1dfa6570e78fa98a40b3fe`，已 push 到 origin。
- Design changes：`docs/design_changes/change_1.md`、`docs/design_changes/change_2.md` 均已入库。

## 遗留问题 / 风险
- 本地系统 Python 受 PEP 668 管理，`pip --user` 被拒；`python3 -m venv` 因缺 `ensurepip` 被拒。已用已安装的 `uv tool run` 隔离执行 ruff/black/mypy/pytest-cov，不污染项目运行时依赖。
- `tools/verify_clangd.py` 作为外部 clangd/LSP 集成资产未纳入 P1 coverage 门槛；后续 P3/P6/P8 真集成时应补对应验证。
- `docs/design_changes/change_1.md` 的两项设计层遗留仍待 design owner 决策：INV14a 冗余注释、`make_error_credibility()` 的 `source=clangd` 占位语义。
- P1 只定义元数据/类型/协议形状，不实现 P2 QR1-9、路由状态机、P3/P4 引擎适配、P5 建库、P6+ API。
- `tools/verify_clangd.py` 与 `tools/cdb_rewriter.py` 已作为复用资产入库；R14 中仅做 ruff/black 机械清理/格式化，未改变 P1 业务逻辑。

## 下一阶段计划
进入 Phase 2：路由判定核心 + QR1-9 容器校验。Phase 2 不得实现 P4 评分算法本身，只读取候选 relevance_score。
