---
name: devmind-git-flow
description: Git and GitHub workflow for the DevMind repo — branch naming, conventional commits, the human-approval rule before any push or PR, PR body template, and draft-only delivery. Use whenever creating a branch, committing, pushing, or opening a pull request in this project.
---

# DevMind Git Flow

## The rule that outranks the rest

**Never push, never open a PR, never merge without the human explicitly asking in this
session.** Approval for one push is not approval for the next one. This is the same guarantee
DevMind itself enforces on its agent; the humans and agents building it hold to it too.

Committing locally on a feature branch is normal work. Anything that leaves the machine is a
separate, explicitly-requested act.

## Branches

Never commit to `main`. Branch first, always.

```
epic/e07-agent-loop-planning        # one epic
feat/e06-f03-apply-patch-tool       # one feature within an epic
fix/pytest-parser-collect-errors    # a defect
docs/solution-design                # docs only
chore/ci-coverage-gate              # tooling
```

Lowercase, hyphenated, ASCII. Include the epic/feature id when the work maps to one — it makes
the branch traceable to `docs/02-epic-breakdown.md`.

```bash
git switch -c epic/e07-agent-loop-planning
```

## Commits

Conventional commits. Subject ≤ 72 chars, imperative mood, no trailing period.

```
<type>(<scope>): <subject>

<body — what changed and *why*; wrap at 72>

<footers>
```

Types: `feat` · `fix` · `refactor` · `test` · `docs` · `chore` · `perf` · `build` · `ci`.
Scope is the epic id or the module: `feat(e08): …`, `fix(tools): …`.

```
feat(e08): add failure-signature no-progress detection

SelfCorrectionController now hashes sorted failing node ids plus exception
types into a stable signature. An identical signature on consecutive attempts
means the last edit changed nothing that mattered, so we escalate to EXHAUSTED
instead of burning the third attempt on the same hypothesis.

Refs: E8-F3-T2
```

End every commit message with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

**Commit hygiene**
- One logical change per commit. A feature and a drive-by refactor are two commits.
- Never commit `.env`, credentials, `*.db`, `__pycache__`, or workspace scratch dirs.
- Run `make check` before committing. A commit that fails lint or types is not done.
- Never `git add -A` blind — `git status` first, stage deliberately.
- Never `git commit --amend` or force-push a branch someone else may have pulled.

## Pull requests

**Preconditions — all four, every time:**
1. The human explicitly asked, in this session, for a PR.
2. `make check` is green and the output was seen, not assumed.
3. The branch is not `main`.
4. `git status` is clean and `git log` shows exactly the intended commits.

```bash
gh pr create --draft \
  --base main \
  --head epic/e07-agent-loop-planning \
  --title "feat(e07): agent loop and planning" \
  --body-file .git/PR_BODY.md
```

**Always `--draft`.** Never `gh pr merge`. Never `--auto`.

### PR body template

```markdown
## Summary
Two or three sentences: what this delivers and why it exists.

## Scope
Epic: E7 — Agent Loop & Planning
Features: E7-F1, E7-F2, E7-F3
Spec: docs/specs/epic-07-agent-loop-planning.md

## Changes
- `services/agent_loop.py` — ReAct loop with per-step event persistence and step budget
- `services/context_compactor.py` — truncation, stale-result clearing, plan re-anchor
- `services/planner_service.py` — issue + repo brief → todo plan

## Testing
```
$ make check
ruff .......... clean
mypy .......... clean
pytest ........ 148 passed in 21.4s
coverage ...... services/ 91%
```

## Standards
Reviewed against `Claude.md`: layer boundaries respected, no new unjustified ABCs,
all closed sets are StrEnums, no inline literals.

## Risks / follow-ups
- Context compaction thresholds are tuned by eye; E12 should measure them against real runs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Before any remote operation — say this out loud

> I am about to run `<exact command>`. The human asked for this in this session at
> `<their words>`. The branch is `<name>`, not main. `make check` passed.

If any clause is false, stop and ask.

## Recovery

| Situation | Do |
|---|---|
| Committed to `main` by mistake | `git branch <name>` then `git reset --hard origin/main` — **only if nothing was pushed** |
| Wrong files staged | `git restore --staged <path>` |
| Need to undo the last local commit | `git reset --soft HEAD~1` |
| Pushed something wrong | **Stop. Tell the human.** Do not force-push to fix it silently |
