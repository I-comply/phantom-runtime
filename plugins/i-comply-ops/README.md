# i-comply-ops skill suite

| Skill | Use |
|---|---|
| ccr-repo-onboarding | Attach, verify, clone and register every repo of an org when gh is unauthenticated |
| ccr-session-cost-report | Totals and per-turn cost; why cost rises |
| ccr-session-handoff-cleanup | Fresh-session handoff, list and archive sessions |
| secret-scan-remediation | Scan working tree and history, correlate by fingerprint, placeholder PRs, rotation guidance |
| pr-watch-recovery | Restore PR monitoring after a session is archived |
| ccr-git-gotchas | Known CCR git/GitHub limits and workarounds |

## Install
- Claude Code (project): copy `skills/*` into `<repo>/.claude/skills/`.
- Claude Code (user): copy `skills/*` into `~/.claude/skills/`.
- Claude Code (plugin): place this folder in a plugin marketplace or load with `--plugin-dir`.
- Claude (claude.ai): Settings > Capabilities > Skills > Upload; one zip per skill (see `zips/`).
