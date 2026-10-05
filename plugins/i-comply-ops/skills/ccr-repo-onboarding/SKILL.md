---
name: ccr-repo-onboarding
description: Audit and attach every repo of a GitHub org in a Claude Code Remote (CCR) session when gh is unauthenticated. Lists repos, attaches private ones, verifies with ls-remote, clones shallow, registers roots, flags empty repos.
---

# CCR repo onboarding

Use when a CCR session must access many repos of one org and `gh` fails (`GH_TOKEN` invalid, GraphQL/org REST 403).

## Steps
1. Record the gh failure verbatim (`gh auth status`, `gh repo list`). Do not retry; org-level REST and GraphQL are blocked in CCR.
2. List repos: `mcp__claude-code-remote__list_repos` (`query: <org>`, `limit: 200`). Record count, name, visibility.
3. Baseline: `GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/<org>/<repo>.git` per repo. Public succeeds. Private fails with `could not read Username ... terminal prompts disabled`.
4. Attach each private repo needed: `add_repo(owner, repo)`. Do not pre-check with curl/gh. If the auto-mode classifier denies (`[Credential Exploration]`), do not work around it; ask the user to re-request.
5. Re-run `ls-remote`. Empty ref list (HTTP 200, no refs) = empty repo.
6. Clone to the path `add_repo` returns (lowercase): `git clone --depth 1 <url> /home/user/<lowercase-name>`; confirm `git rev-parse HEAD` equals the ls-remote SHA.
7. `register_repo_root(owner, repo, directory)` after each successful clone. It fails if the repo is not in session sources; run `add_repo` first, then retry.
8. Skip registration for empty clones (only `.git`; warning "You appear to have cloned an empty repository").

## Gotchas
- Public repos need no `add_repo` for read.
- Attach only repos the task needs: each repo adds context and cost.
- Paths are lowercase even if the repo name is mixed case.
