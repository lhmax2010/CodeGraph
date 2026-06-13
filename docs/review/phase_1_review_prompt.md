# Phase 1 Review Prompt

## 范围
CodeGraph Phase 1：元数据层 + 数据结构 + 引擎观察协议。

按用户最新流程，本项目只 push，不创建 PR。

## 变更文件
- `codegraph/credibility.py`
- `codegraph/factories.py`
- `codegraph/types.py`
- `codegraph/engines/protocol.py`
- `tests/test_phase1_metadata.py`
- `tests/test_credibility.py`
- `tests/test_cdb_rewriter.py`
- `tools/cdb_rewriter.py`
- `tools/verify_clangd.py`
- `codegraph/__init__.py`
- `.gitignore`
- `docs/reuse-assets.md`
- `.dev_memory/INDEX.md`
- `.dev_memory/stage01_metadata/progress.md`
- `.dev_memory/stage01_metadata/result.md`

## 设计依据
- `docs/design.md` §4.1 数据结构。
- `docs/design.md` §4.2 Credibility schema + INV1-16/18/19。
- `docs/design.md` §7 Phase 1。
- `docs/CodeGraph-SOP部署开发Guide.md` §5 CodeGraph 硬约束。

## Review 重点
- 是否只做 P1 范围：不得混入 QR1-9、路由状态机、具体 clangd/tree-sitter 适配、API 端到端、MCP。
- INV17 是否正确留给 P2 QR7，而不是在 `check_invariants()` 中误做。
- `QueryMeta` 是否为 `@dataclass(frozen=True)`，字段为 kind/symbol/build_config_id 必填，file/pos 可选。
- 预留值处理是否正确：`log_search`/`exact_syntactic` 放行合法组合，不写死 MVP 白名单；INV19 校验 exact_syntactic=>log_search。
- `make_error_credibility()` 是否匹配 §4.3 的 FAILED/INVALID_REQUEST 最小占位。
- 旧 28 个 credibility 测试是否仍全过。
- 核心模块是否保持纯 stdlib。

## 已执行命令
- `PYTHONPATH=.:tools python3 -m pytest tests/ -q`
  - 结果：65 passed in 0.07s。
- `PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q`
  - 结果：28 passed in 0.02s。
- `python3 -m compileall -q codegraph tools tests`
  - 结果：通过，无输出。
- `/home/linhao/.local/bin/uv tool run ruff check .`
  - 结果：All checks passed。
- `/home/linhao/.local/bin/uv tool run black --check .`
  - 结果：11 files would be left unchanged。
- `/home/linhao/.local/bin/uv tool run mypy codegraph`
  - 结果：Success, no issues found in 6 source files。
- `PYTHONPATH=.:tools /home/linhao/.local/bin/uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing`
  - 结果：65 passed；`codegraph` coverage total 97%。

## Coverage 例外
- 全仓库 `--cov=codegraph --cov=tools` 已执行且测试通过，但 total coverage 为 58%。
- 原因：`tools/verify_clangd.py` 是外部 clangd/LSP 集成资产，P1 不启动 clangd 子进程或真机环境；该路径留到 P3/P6/P8 集成验证。

## Review 输出格式
请按严重程度标注：
- `[BLOCKER]`
- `[MAJOR]`
- `[MINOR]`
- `[NIT]`

并标注类型：
- `[CODE_ISSUE]`
- `[DESIGN_SUGGESTION]`
- `[ALTERNATIVE]`
