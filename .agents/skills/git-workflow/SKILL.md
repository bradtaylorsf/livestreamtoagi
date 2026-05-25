---
name: git-workflow
description: Git branch naming, commit conventions, and PR workflow. Use for all git operations.
auto_load: true
priority: high
---

# Git Workflow Skill

## Trigger
When creating branches, writing commits, or creating PRs.

## Branch Naming

```
agent/issue-{number}     # automated loop branches
feat/{description}       # feature branches
fix/{description}        # bug fix branches
```

## Commit Conventions

Use conventional commits:

```
feat: add health check endpoint (closes #1)
fix: resolve test failures for #3
test: add unit tests for runner module
refactor: simplify prompt building
docs: update CLAUDE.md with new skills
chore: update dependencies
```

Rules:
- Lowercase, no period at end
- Reference issue number when applicable
- One logical change per commit
- Commit message explains WHY, diff shows WHAT

## PR Workflow

1. Branch from the target branch (master or session branch)
2. Implement + test + commit
3. Push branch
4. Create PR with: summary, test results, review report
5. Link PR to issue with `closes #N`

## Never Do

- Force push to master/main
- Commit directly to master/main
- Commit .env files or secrets
- Create merge commits (use squash merge)
- Commit `.venv` symlinks — `.gitignore`'s `.venv/` directory entry does not cover a same-name symlink. Run `git ls-files | grep -E '(^|/)\.?venv($|/)'` before committing and `git rm --cached .venv` if any appear.

## Retry Commit Hygiene

When fixing review findings or re-running tests in the loop, each retry commit must NAME the specific fix. Past sessions had three identical `fix: resolve verification failures` messages on the same PR, making the retry log unreadable.

Good:
```
fix: address review findings for #410 — populate PublicEvalRunDetail.status
fix: address review findings for #410 — wire scenario_id into initial fetch
fix: address review findings for #410 — replace — with em-dash in JSX
```

Bad:
```
fix: resolve verification failures
fix: resolve verification failures
fix: resolve verification failures
```

If you genuinely can't summarize what changed in a retry, you don't yet understand the fix — stop and re-read the diff before committing.
