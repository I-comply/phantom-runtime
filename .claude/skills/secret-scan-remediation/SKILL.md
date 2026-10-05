---
name: secret-scan-remediation
description: Scan local git clones for committed secrets (working tree and full history), correlate identical secrets across repos by fingerprint, and open draft PRs that replace exposed values with placeholders. Use for secret audits, leaked key cleanup, and pre-rotation triage. Never rewrites history without explicit approval.
---

# Secret scan and remediation

## 1. Scan (read-only)
1. Make clones complete: `git fetch --unshallow origin` for shallow clones, and `git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` then `git fetch origin` so `--all` covers every branch.
2. Run `python3 scripts/scan.py <dir containing clones> --history`. Output per repo: file, line, rule, commit, fingerprint. It never prints secret values.
3. Without `--history` only current files are checked. Always run the history pass before reporting.
4. Matches are regex hits (AWS, GitHub, Anthropic/OpenAI/Emergent, Stripe, Slack, Google, private keys, generic assignments). Absence of findings is not proof of absence.

## 2. Triage
- Equal fingerprints in several repos = the same secret. One rotation covers them all.
- A `.env` found only in history was committed then deleted; it is still exposed.
- Classify unidentified generic hits as live until the owner confirms otherwise.
- Never paste secret values into chat, PRs or files. Mask to the first 3 characters if a value must be referenced.

## 3. Remediate (needs user approval for each step)
1. Rotate first. Only the owner can; removing a value from files does not revoke it.
2. Draft PR per repo on a branch such as `claude/remove-exposed-<name>`: replace the value with a placeholder like `<your-key-name>`. State in the PR body that the value remains in history and must be rotated.
3. Check replacements in config files (for example `${VAR:-default}` in compose files): a placeholder default means the variable must now be set in the environment. Say so in the PR.
4. Optional: PR adding `.env` to `.gitignore`.
5. History rewrite (filter-repo or BFG plus force-push) is destructive: it breaks clones and open PRs. Do not do it without explicit approval, and only after rotation.

## 4. Report
Per repo: count of findings, fingerprints, whether history is affected, PR links. List what only the user can do (rotate, archive repos, merge PRs).
