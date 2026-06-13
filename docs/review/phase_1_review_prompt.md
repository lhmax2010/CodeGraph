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
  - 结果：59 passed in 0.05s。
- `PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q`
  - 结果：28 passed in 0.02s。
- `python3 -m compileall -q codegraph tools tests`
  - 结果：通过，无输出。

## 未完成 Gate
- `ruff check`：本机无 `ruff`。
- `black --check .`：本机无 `black`。
- `mypy codegraph`：本机无 `mypy`。
- `pytest --cov`：本机无 `pytest-cov`。

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
