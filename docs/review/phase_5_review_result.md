# Phase 5 Review Result

## Scope
- Branch: `phase/5-index-build`
- Final reviewed HEAD: `536b521 [Phase 5] fix: handle relative CDB paths and index build failures`
- Base: `origin/main` at Phase 4 checkpoint
- Review mode: no PR created; review artifacts only, per user rule.

## Gate Results
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `108 passed in 1.42s`
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_indexing.py -q` -> `11 passed in 1.28s`
- `PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing` -> `108 passed`, total coverage 92%, `codegraph/indexing.py` 90%
- `.venv/bin/ruff check .` -> `All checks passed!`
- `.venv/bin/black --check .` -> `20 files would be left unchanged`
- `.venv/bin/mypy codegraph` -> `Success: no issues found in 10 source files`
- `.venv/bin/python -m compileall -q codegraph tools tests` -> passed

## First Review Round
Three routes were run before final review:
- Local checklist/self-review.
- Independent Codex subagent review.
- Claude CLI review via tool-less `claude -p`.

Findings fixed before final review:
- `[BLOCKER/MAJOR]` Relative `compile_commands.json` `file` paths were resolved against process cwd instead of entry `directory`, which could undercount `unique_TU` and make `shards >= unique_TU` too optimistic.
  - Fix: added `_entry_file_path()` and reused it in `summarize_compile_commands()` and `_default_trigger_files()`.
  - Tests: relative same-basename TUs in different directories; missing `file` entry is excluded.
- `[MAJOR]` clangd startup/LSP errors could raise through `run_background_index()` and make `tools/build_index.py` traceback instead of producing structured `UNKNOWN`.
  - Fix: `run_background_index()` catches build-stage exceptions and returns `IndexHealth.UNKNOWN` with reason `index_build_failed`.
  - Tests: missing clangd direct API path and CLI path.
- `[MINOR]` CLI subprocess tests hardcoded `.venv/bin/python`.
  - Fix: subprocess tests now use `sys.executable`.
  - Verification: CLI tests also passed from `/tmp`, not just repo root.

## Final Review Round

### Local Review
Status: no blocking issues.

Confirmed:
- P5 still only emits `index_health` facts and does not judge `not_found`.
- Lower-bound criterion remains `idx_shards >= unique_TU_count`; no ratio threshold added.
- CLI tests use `sys.executable`.
- `PYTHONPATH=/home/linhao/Toolchain/development/CodeGraph:/home/linhao/Toolchain/development/CodeGraph/tools /home/linhao/Toolchain/development/CodeGraph/.venv/bin/python -m pytest /home/linhao/Toolchain/development/CodeGraph/tests/test_indexing.py -q -k 'build_index_cli'` from `/tmp` -> `3 passed, 8 deselected in 0.69s`.

### Codex Subagent Review
Status: no blocking issues.

Confirmed:
- Relative `file` paths now resolve against CDB entry `directory`; missing `file` returns `None` and is not counted in `unique_tu_count`.
- clangd startup/LSP exceptions now degrade to `IndexHealth.UNKNOWN/index_build_failed`; CLI still emits JSON.
- CLI tests no longer hardcode `.venv/bin/python`.
- P5 still does not add not_found/negative-proof logic.

### Claude CLI Review
Status: no blocking issues.

Confirmed:
- Scope remains offline build + `index_health`.
- No `not_found` judgment appears in `codegraph/indexing.py` or `tools/build_index.py`.
- Lower-bound logic remains `idx_shards < unique_TU_count -> incomplete`, otherwise complete.
- Relative `file` and missing-file handling are fixed and tested.
- clangd build errors degrade to `UNKNOWN`, and CLI still emits JSON for the tested build-error path.
- CLI tests use `sys.executable`.

Non-blocking observations retained for later consideration:
- `existing_files` is intentionally not used as the health denominator; stale CDBs can become false incomplete, not false complete.
- `.idx` shard count may include header shards; this is the design-mandated lower-bound heuristic and remains a known limitation without per-TU ledger.
- Malformed/missing CDB and CDB rewrite errors can still traceback instead of JSON; this is outside the reviewed clangd-build-error requirement.
- The minimal LSP client drops server-to-client requests; current smoke/CLI tests pass, but this may need hardening if future clangd versions block on those requests.

## Final Verdict
Phase 5 implementation is review-clean for the current development gate.

Remaining non-code gate before P5 merge: run one full ARM rebuild from CDB to `.idx` after the user confirms the time window, then record build/load timing in `.dev_memory/stage05_index_build/result.md`.
