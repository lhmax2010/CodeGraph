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
