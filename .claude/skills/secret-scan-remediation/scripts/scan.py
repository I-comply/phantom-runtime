#!/usr/bin/env python3
"""Read-only secret scanner. Scans working trees (and optionally full git history) of local clones.
Never prints secret values; reports repo, file, line, rule only."""
import hashlib, os, re, subprocess, sys, json
RULES = {
    "aws-access-key": r"AKIA[0-9A-Z]{16}",
    "github-token": r"gh[pousr]_[A-Za-z0-9]{36,}",
    "anthropic-key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "openai-key": r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    "emergent-key": r"sk-emergent-[A-Za-z0-9]{8,}",
    "stripe-key": r"(?:sk|rk)_live_[A-Za-z0-9]{16,}",
    "slack-token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private-key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "google-api-key": r"AIza[0-9A-Za-z_-]{35}",
    "generic-assignment": r"(?i)(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]",
}
RX = {k: re.compile(v) for k, v in RULES.items()}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
PLACEHOLDER = re.compile(r"(?i)(your[_-]?|example|placeholder|changeme|xxxx|<.*>|\$\{|os\.environ|process\.env)")

def fp(v):
    return hashlib.sha256(v.encode()).hexdigest()[:8]

def scan_text(name, text, hits):
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 2000: continue
        for rule, rx in RX.items():
            m = rx.search(line)
            if m and not PLACEHOLDER.search(m.group(0)):
                hits.append({"file": name, "line": i, "rule": rule, "fp": fp(m.group(0))})

def scan_tree(repo):
    hits = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) > 1_000_000: continue
                with open(p, "r", encoding="utf-8", errors="strict") as fh:
                    scan_text(os.path.relpath(p, repo), fh.read(), hits)
            except (UnicodeDecodeError, OSError):
                continue
    return hits

def scan_history(repo):
    hits = []
    try:
        out = subprocess.run(["git", "-C", repo, "log", "-p", "--all", "--no-color", "-U0"],
                             capture_output=True, text=True, errors="replace", timeout=300).stdout
    except Exception:
        return hits
    cur = commit = ""
    for line in out.splitlines():
        if line.startswith("commit "): commit = line[7:]
        elif line.startswith("+++ b/"): cur = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            for rule, rx in RX.items():
                m = rx.search(line)
                if m and not PLACEHOLDER.search(m.group(0)):
                    hits.append({"file": cur, "line": 0, "rule": rule + " (history)", "commit": commit[:8], "fp": fp(m.group(0))})
    return hits

if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "/home/user"
    history = "--history" in sys.argv
    report = {}
    for d in sorted(os.listdir(base)):
        repo = os.path.join(base, d)
        if not os.path.isdir(os.path.join(repo, ".git")): continue
        hits = scan_tree(repo)
        if history: hits += scan_history(repo)
        seen, uniq = set(), []
        for h in hits:
            k = (h["file"], h["rule"], h.get("fp"))
            if k not in seen: seen.add(k); uniq.append(h)
        report[d] = uniq
    json.dump(report, open("scan_report.json", "w"), indent=1)
    for r, h in report.items():
        print(f"{r}: {len(h)} finding(s)")
        for x in h[:15]: print(f"   {x['file']}:{x['line']}  {x['rule']}  fp={x.get('fp')}" + (f" commit={x['commit']}" if 'commit' in x else ""))
