---
name: ccr-git-gotchas
description: Known limits and workarounds in Claude Code Remote (CCR) cloud sessions for git and GitHub work: blocked API paths, repo settings writes, invalid GH_TOKEN, classifier denials, shallow-clone refspec, stop-hook complaints about unpushed branches. Use when a git or GitHub command fails unexpectedly in a CCR session.
---

# CCR git and GitHub gotchas

| Symptom | Cause | Action |
|---|---|---|
| `gh`: "The token in GH_TOKEN is invalid" | Container env token is stale; a renewed token elsewhere does not reach the container | Use `list_repos`, `add_repo` and `mcp__github__*`. Tell the user the container env needs updating. |
| HTTP 403 "This GitHub API path is not available: sessions are bound to their configured repositories" | Org-level REST/GraphQL blocked | Use repo-scoped endpoints or `list_repos`. |
| HTTP 403 "Repository settings writes are not permitted through this proxy" | Archiving, visibility and similar settings are blocked | Do not retry or work around it. The user does it in GitHub (Settings). |
| `fatal: could not read Username ... terminal prompts disabled` | Private repo not attached | `add_repo` first, then retry. |
| `add_repo` denied `[Credential Exploration]` | Auto-mode classifier | Do not work around it; ask the user to re-request. |
| `register_repo_root` fails: repo not in session sources | Repo not attached | `add_repo`, then retry. |
| Push needs credentials | `add_repo` defaults to read | Call `add_repo` with `access: "push"`. |
| Stop hook: "branch has N unpushed commit(s) and no remote branch" although push succeeded | Shallow clone fetches only `main`, so git has no remote-tracking ref | `git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` then `git fetch origin`. Verify with `git status -sb` showing `...origin/<branch>`. |
| Cost per turn keeps rising | Whole context is reread each turn | See `ccr-session-cost-report`; hand off with `ccr-session-handoff-cleanup`. |

## Habits
- Draft PR after every push to a designated branch; then `subscribe_pr_activity`.
- Commit attribution lines come from the session system reminder; use them verbatim.
- Do not read or print token values. If a credential is missing, report it.
