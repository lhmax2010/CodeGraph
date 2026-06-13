# Phase 1 Review Result

## gstack-claude Review

- Tool path: installed gstack with `./setup --host codex --prefix`; invoked the generated `/gstack-claude` workflow manually from this API session by running nested `claude -p`.
- Mode: Review mode, tool-less nested Claude (`--disable-slash-commands --tools ""`).
- Base diff: `git diff origin/main` from branch `phase/1-metadata`.
- Status: Completed.

## Verdict

No `[BLOCKER]` findings. Claude reported that the main Phase 1 frozen-contract requirements are met:
- P1 scope is limited to metadata schema, data structures, factories, and engine observation protocols.
- INV17 is correctly absent from `check_invariants` because it belongs to P2 QR7.
- `QueryMeta` is `@dataclass(frozen=True)`.
- `log_search` / `exact_syntactic` reserved values are accepted where legal, and INV19 rejects illegal exact_syntactic sources.
- No P2+ routing/API/MCP logic leaked into `codegraph/`.

## Findings

### [MAJOR] [CODE_ISSUE] `consumer_hint: Optional[dict]` weakens frozen/immutable behavior

`Credibility.consumer_hint` is typed as a mutable dict inside a frozen dataclass. If populated, the dict remains mutable and can also make `Credibility` unhashable if used in hashed contexts. Suggested options:
- Use an immutable representation.
- Or set `compare=False, hash=False` and document `consumer_hint` as opaque/non-hash-participating.

### [MAJOR] [DESIGN_SUGGESTION] Deterministic gate gap remains

`ruff`, `black`, `mypy`, and `pytest-cov` were not run because the tools are missing locally. Claude called this a real gate gap for a type/schema-heavy phase, especially around mypy. This is environment/tooling, but it should be resolved before treating P1 as fully closed.

### [MINOR] [CODE_ISSUE] `_check_inv14a` is unreachable after INV13

`NegativeScope` only has `current_tu`, `indexed_project`, and `none`. `_check_inv13` rejects `none` for `not_found` before `_check_inv14a` runs, so `_check_inv14a` cannot currently raise.

### [MINOR] [CODE_ISSUE] PEP604 guard test may overstate future-import safety

`ResultData = LocationResult | ...` and `CandidateData = ...` are runtime type alias assignments, not annotations. `from __future__ import annotations` does not defer those. This is fine for Python 3.10+ but the guard test should not imply future import protects runtime aliases.

### [MINOR] [CODE_ISSUE] `clangd_relation_must` docstring overclaims dependency completeness

The docstring says it requires a complete dependency closure, but neither the factory nor an invariant enforces `dep.status == COMPLETE`.

### [MINOR] [DESIGN_SUGGESTION] Enum/string representation drift risk

Examples:
- `Credibility.index_health: IndexHealth` vs `QueryResult.index_health: Literal[...]`
- `SymbolKind` enum vs `LocationResult.kind: str`
- `QueryKind` enum vs `QueryMeta.kind: str`

Claude suggested pinning equality/mapping in tests if the frozen contract intentionally keeps string forms.

### [MINOR] [CODE_ISSUE] `make_error_credibility` attributes errors to clangd

`make_error_credibility()` uses `source=clangd` for INVALID_REQUEST/FAILED placeholders, which is invariant-legal but semantically not fully neutral. Claude suggested surfacing this to the design owner because there is no `Source.UNKNOWN` / `NONE`.

### [MINOR] [CODE_ISSUE] Thin tests on protocol shapes and some helper behavior

Claude called out:
- Protocol exports are only checked for non-None, not conformance by a stub.
- No explicit test for legal `log_search + syntactic`.
- No explicit test that `validate()` returns the same object.

### [NIT] Invariant order is load-bearing

Legacy tests depend on INV6/INV7 firing before newer not_found coverage invariants. Claude suggested adding a comment that the order is intentional.

### [NIT] Result containers are mutable while `QueryMeta` is frozen

This is contract-compliant, but the difference should be intentional.

### [NIT] Misc

- `codegraph/__init__.py` docstring was removed during asset import.
- Dev-memory drift: `progress.md` still had an older "59 tests" log while result/review prompt now say 60.

### Out of P1 Scope

`tools/cdb_rewriter.py` uses `os.path.exists()` inside rewrite logic, which may conflict with its "pure function/no filesystem side effects" docstring. Since this is a P5 reuse asset and unchanged in P1, Claude marked it for later P5 review rather than a P1 blocker.

## Required Closure

Per SOP R14:
- `[MAJOR]` findings need fixes or explicit developer waiver before Phase 1 is considered review-closed.
- `[MINOR]` findings can be fixed now or recorded as TODOs.
- `[NIT]` findings are optional unless the developer chooses to tighten polish now.

## R14 Closure Update - 2026-06-13

Status: Phase 1 review findings are closed. No PR was created, per user override; closure is via pushed branch + review artifacts.

### Major Findings

- `[MAJOR] consumer_hint mutable/hash risk`: Fixed.
  - `Credibility.consumer_hint` remains the frozen-contract `dict | None` style extension point, but is now declared with `field(default=None, compare=False, hash=False)`.
  - Added regression coverage proving a populated mutable hint does not affect equality/hash stability.
- `[MAJOR] deterministic gate gap`: Fixed for P1 scope.
  - Direct `pip --user` install was blocked by PEP 668; local `venv` was blocked by missing `ensurepip`; deterministic tools were run through installed `uv tool run` instead.
  - `ruff`, `black`, `mypy`, and `pytest-cov` all ran successfully.
  - Full `--cov=codegraph --cov=tools` was executed and passed tests, but total coverage is 58% because `tools/verify_clangd.py` is an external clangd/LSP integration asset with no P1 local runtime coverage. P1 core coverage was therefore measured with `--cov=codegraph`: 97%.

### Minor / Nit Findings

- `_check_inv14a` reachability: No code change. It is retained as the dedicated INV14a checker required by design; while enum-typed normal construction reaches INV13 first for `none`, the checker still documents the frozen invariant and can catch non-enum runtime values.
- PEP604 guard wording/logic: Fixed. The guard now checks annotation syntax only and no longer treats runtime type aliases as future-import-protected annotations.
- `clangd_relation_must` docstring overclaim: Fixed. The docstring now states caller responsibility and notes the factory does not enforce `dep.status=complete`.
- Enum/string representation drift risk: Fixed with a regression test pinning `QueryKind`, `SymbolKind`, and `IndexHealth` string values at public container boundaries.
- `make_error_credibility()` source attribution: No code change. Design §4.3 explicitly specifies `source=clangd` for the neutral FAILED/INVALID_REQUEST placeholder; changing it would require an R1 design change.
- Thin protocol/helper tests: Fixed. Added a minimal protocol stub test, legal `log_search + syntactic` coverage, and `validate()` identity coverage.
- Invariant order is load-bearing: Fixed with an explicit comment above `_INVARIANT_CHECKS`.
- Mutable result containers vs frozen `QueryMeta`: No code change. This is contract-compliant per design §4.1.2; P2 will enforce container invariants.
- `codegraph/__init__.py` docstring removed: Fixed.
- Dev-memory drift: Fixed in progress/result updates; latest all-test count is 65.
- P5 follow-up: `tools/cdb_rewriter.py` filesystem behavior remains recorded as out-of-P1 scope for P5 review.

### Closure Commands

- `/home/linhao/.local/bin/uv tool run ruff check .`
  - Result: `All checks passed!`
- `/home/linhao/.local/bin/uv tool run black --check .`
  - Result: `11 files would be left unchanged.`
- `/home/linhao/.local/bin/uv tool run mypy codegraph`
  - Result: `Success: no issues found in 6 source files`
- `PYTHONPATH=.:tools python3 -m pytest tests/ -q`
  - Result: `65 passed in 0.07s`
- `PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q`
  - Result: `28 passed in 0.02s`
- `python3 -m compileall -q codegraph tools tests`
  - Result: passed with no output.
- `PYTHONPATH=.:tools /home/linhao/.local/bin/uv tool run --with pytest-cov pytest tests/ -q --cov=codegraph --cov-branch --cov-report=term-missing`
  - Result: `65 passed`; `codegraph` coverage total `97%`.
