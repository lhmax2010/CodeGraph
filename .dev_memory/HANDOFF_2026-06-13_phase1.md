# Handoff - Phase 1 Metadata

Date: 2026-06-13
Branch: `phase/1-metadata`
Remote state: pushed to `origin/phase/1-metadata`
Latest commit at handoff: `c8ee620 [Phase 1] docs: record gstack Claude review findings`

## Current State

Phase 1 implementation is complete but not review-closed.

Implemented:
- Reuse assets imported and verified:
  - `codegraph/credibility.py`
  - `codegraph/factories.py`
  - `tests/test_credibility.py`
  - `tests/test_cdb_rewriter.py`
  - `tools/cdb_rewriter.py`
  - `tools/verify_clangd.py`
- P1 metadata work:
  - `codegraph/credibility.py`: schema fields + INV13-16/18/19.
  - `codegraph/factories.py`: expanded factories + `make_error_credibility()`.
  - `codegraph/types.py`: §4.1 dataclasses/enums; `QueryMeta` is frozen dataclass.
  - `codegraph/engines/protocol.py`: `EngineObservation` / `SyntacticProvider`.
  - `tests/test_phase1_metadata.py`: P1 tests, including future annotations guard.
- gstack Claude review was completed and recorded:
  - `docs/review/phase_1_review_result.md`

User override:
- Do not create PRs for this project.
- Use `git push` only.
- SOP PR gates should be treated as push + review artifact gates.

## Verified Commands

Last known passing checks:

```bash
PYTHONPATH=.:tools python3 -m pytest tests/ -q
# 60 passed

PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q
# 28 passed

python3 -m compileall -q codegraph tools tests
# passed
```

Known missing tools at the time of handoff:
- `ruff`
- `black`
- `mypy`
- `pytest-cov`

## gstack / Claude State

Installed during the previous session:
- Bun: `1.3.14`
- Claude Code CLI: `2.1.177`
- Codex CLI: `0.139.0`
- gstack installed with:

```bash
cd ~/gstack
PATH="$HOME/.bun/bin:$PATH" ./setup --host codex --prefix
```

Successful setup marker:
- `gstack ready (codex)`
- Skills linked under `~/.codex/skills/`
- `skill_prefix=true`, so command names are `/gstack-*`.
- `/gstack-claude` exists and was used via its underlying CLI instructions.

Important nuance:
- The old API session could not hot-refresh newly installed skills, so it manually followed `~/.codex/skills/gstack-claude/SKILL.md`.
- A new Codex session should see the installed `/gstack-*` skills natively.

## gstack Review Result Summary

`docs/review/phase_1_review_result.md` contains the full review.

Claude reported no `[BLOCKER]`.

Open `[MAJOR]` findings:
1. `[MAJOR] [CODE_ISSUE] consumer_hint: Optional[dict] weakens frozen/immutable behavior`
   - `Credibility.consumer_hint` is mutable inside a frozen dataclass and may affect hashability.
   - Suggested fix: immutable representation, or `field(compare=False, hash=False)` and document opaque semantics.
2. `[MAJOR] [DESIGN_SUGGESTION] deterministic gate gap remains`
   - `ruff`, `black`, `mypy`, `pytest-cov` were missing.
   - Need install/configure tooling or get explicit user waiver before marking P1 review-closed.

Open `[MINOR]` / `[NIT]` findings include:
- `_check_inv14a` is unreachable after INV13.
- PEP604 guard test wording/logic overstates future import safety for runtime type aliases.
- `clangd_relation_must` docstring overclaims dependency completeness.
- Enum/string representation drift risk.
- `make_error_credibility()` uses `source=clangd` for neutral errors.
- Protocol tests are thin.
- Add comment that invariant order is load-bearing.
- `codegraph/__init__.py` docstring removed.
- `progress.md` has an old "59 tests" line while latest result is 60.
- P5 follow-up: `tools/cdb_rewriter.py` uses `os.path.exists()` despite its pure-function docstring.

## Recommended Next Step

Start with R14 review closure for Phase 1.

Do not start Phase 2 yet.

Suggested flow:
1. Read:
   - `AGENTS.md`
   - `docs/design.md`
   - `.dev_memory/INDEX.md`
   - `.dev_memory/stage01_metadata/result.md`
   - `docs/review/phase_1_review_result.md`
2. Confirm current branch/status:
   - `git branch --show-current`
   - `git status --short --branch`
   - `git log --oneline -8`
3. Ask user whether to fix both `[MAJOR]` findings now or waive any.
4. If fixing:
   - Keep edits in P1 scope.
   - Record decisions in `.dev_memory/stage01_metadata/progress.md`.
   - Run tests.
   - Commit and `git push`.
5. After `[MAJOR]` closure, optionally run `/gstack-claude review` again or manually follow the skill if slash command is unavailable.

## Boundaries To Preserve

- Do not modify `docs/design.md`.
- Do not implement P2 QR1-9 in P1.
- Do not implement routing state machine.
- Do not implement concrete clangd/tree-sitter adapters.
- Do not implement API endpoints, offline indexing, or MCP.
- INV17 remains P2 QR7, not P1 `check_invariants`.
- QueryMeta must remain `@dataclass(frozen=True)`.
- Core modules stay pure stdlib.
- Use `git push`, not PR creation.
