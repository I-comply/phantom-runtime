#!/usr/bin/env python3
"""Read-only source inventory for the PhantomworX + i-Comply portfolio pipeline.

Usage: inventory.py --root DIR [--out FILE] [--exclude NAME ...]
Each immediate subdirectory of DIR that is a git clone is inventoried. Nothing is
modified. Secret scanning records file path, line and rule only, never the value.
"""
import argparse, json, os, re, subprocess, sys, datetime, collections

LANG = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".sql": "SQL", ".sh": "Shell", ".yml": "YAML", ".yaml": "YAML", ".md": "Markdown",
        ".json": "JSON", ".css": "CSS", ".html": "HTML", ".prisma": "Prisma", ".go": "Go", ".java": "Java"}
CODE = {"Python", "JavaScript", "TypeScript", "SQL", "Shell", "Go", "Java", "Prisma"}
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "Pipfile", "go.mod", "pom.xml", "Dockerfile",
             "docker-compose.yml", "package-lock.json", "yarn.lock", "render.yaml", "vercel.json"}
SECRET_RULES = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("stripe-live-key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("emergent-key", re.compile(r"\bsk-emergent-[A-Za-z0-9]+\b")),
    ("generic-assigned-secret", re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{20,}['\"]")),
]
TEST_RE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]+\.py$|\.(test|spec)\.[jt]sx?$|_test\.py$")
LICENSE_HINT = re.compile(r"(?i)^(licen[cs]e|copying)")


def git(repo, *a):
    try:
        return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


def inventory_repo(path):
    files = [f for f in git(path, "ls-files").splitlines() if f]
    langs = collections.Counter(); loc = collections.Counter(); tests = 0; manifests = []; licenses = []
    secrets = []
    for f in files:
        ext = os.path.splitext(f)[1].lower(); lang = LANG.get(ext)
        base = os.path.basename(f)
        if base in MANIFESTS: manifests.append(f)
        if LICENSE_HINT.match(base) and "/" not in f: licenses.append(f)
        if TEST_RE.search(f) and lang in CODE: tests += 1
        full = os.path.join(path, f)
        try:
            if os.path.getsize(full) > 2_000_000 or os.path.islink(full): continue
            data = open(full, "rb").read()
        except OSError:
            continue
        if b"\0" in data[:4096]: continue
        text = data.decode("utf-8", "replace")
        if lang: langs[lang] += 1
        if lang in CODE: loc[lang] += text.count("\n") + 1
        for i, line in enumerate(text.splitlines(), 1):
            if len(line) > 4000: continue
            for rid, rx in SECRET_RULES:
                if rx.search(line):
                    secrets.append({"rule": rid, "path": f, "line": i})
    readme = next((f for f in files if f.lower() == "readme.md"), None)
    head = ""
    if readme:
        head = open(os.path.join(path, readme), encoding="utf-8", errors="replace").read(600)
    authors = collections.Counter(git(path, "log", "--format=%an").splitlines())
    return {
        "source_id": os.path.basename(path.rstrip("/")),
        "locator": git(path, "remote", "get-url", "origin") or path,
        "commit_sha": git(path, "rev-parse", "HEAD"),
        "last_commit_date": git(path, "log", "-1", "--format=%cI"),
        "shallow": git(path, "rev-parse", "--is-shallow-repository") == "true",
        "commit_count_visible": len(git(path, "log", "--format=%H").splitlines()),
        "authors_visible": dict(authors),
        "file_count": len(files),
        "languages_files": dict(langs),
        "code_loc": dict(loc),
        "test_file_count": tests,
        "manifests": manifests[:40],
        "license_files": licenses,
        "secret_scan": {"findings": len(secrets), "details": secrets[:50],
                        "note": "pattern-based; values never recorded; verify each finding manually"},
        "readme_head": head,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out")
    ap.add_argument("--exclude", nargs="*", default=[])
    a = ap.parse_args()
    out = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "root": a.root, "repos": []}
    for name in sorted(os.listdir(a.root)):
        p = os.path.join(a.root, name)
        if name in a.exclude or not os.path.isdir(p): continue
        if not (os.path.isdir(os.path.join(p, ".git")) or os.path.isfile(os.path.join(p, ".git"))): continue
        out["repos"].append(inventory_repo(os.path.realpath(p) if os.path.islink(p) else p))
    s = json.dumps(out, indent=2, sort_keys=True)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w").write(s + "\n")
    else:
        print(s)


if __name__ == "__main__":
    sys.exit(main())
