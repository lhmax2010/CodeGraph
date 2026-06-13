# New Session Prompt

Copy this prompt into the new Codex session:

```text
We are continuing CodeGraph development in /home/linhao/Toolchain/development/CodeGraph.

Important project rule from the user: do not create PRs. Use git push only. If SOP/AGENTS says PR, treat that as push + review artifacts instead.

First, load context in this order:
1. AGENTS.md
2. docs/design.md
3. docs/CodeGraph-SOP部署开发Guide.md
4. .dev_memory/INDEX.md
5. .dev_memory/HANDOFF_2026-06-13_phase1.md
6. .dev_memory/stage01_metadata/result.md
7. docs/review/phase_1_review_result.md
8. docs/review/phase_1_review_prompt.md

Then verify state:
- git branch --show-current
- git status --short --branch
- git log --oneline -8
- PYTHONPATH=.:tools python3 -m pytest tests/ -q

Current expected branch:
- phase/1-metadata

Current expected latest commit before you do any work:
- c8ee620 [Phase 1] docs: record gstack Claude review findings

Current status:
- Phase 1 implementation is complete but not review-closed.
- gstack was installed with host=codex and prefix=true.
- New session should see /gstack-* skills, especially /gstack-claude.
- If slash skills are unavailable, read ~/.codex/skills/gstack-claude/SKILL.md and follow its Review Mode manually.

Do not start Phase 2 yet.

Primary task:
Close Phase 1 review per R14 using docs/review/phase_1_review_result.md.

Open [MAJOR] findings:
1. consumer_hint: Optional[dict] weakens frozen/immutable behavior in Credibility.
   Decide with the user whether to fix by making it immutable or by excluding it from compare/hash and documenting opaque semantics.
2. deterministic gate gap remains because ruff/black/mypy/pytest-cov were missing.
   Try to install/configure local dev tooling if reasonable, or ask the user for an explicit waiver if tooling cannot be added now.

Open [MINOR]/[NIT] findings are in docs/review/phase_1_review_result.md. Do not fix broad or design-affecting items without user confirmation.

When making fixes:
- Stay in Phase 1 scope only.
- Do not modify docs/design.md.
- Record decisions immediately in .dev_memory/stage01_metadata/progress.md.
- Run tests and any available deterministic gates.
- Commit with a Phase 1 commit message.
- git push.
- Do not create a PR.

After fixing or getting waivers for [MAJOR] findings, rerun /gstack-claude review or manually run the nested Claude review path, then report remaining findings and wait for user decision before Phase 2.
```
