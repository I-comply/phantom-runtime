"""File discovery, parallel scanning, suppression, baselines and diff filtering."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import re
import signal
import subprocess
import sys
import time

from . import lang as L
from . import matcher as M
from . import rules as R
from . import secrets as S
from .engine import Engine, run_rule, Finding

DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", ".venv", "venv", "env", "__pycache__",
                        ".next", ".nuxt", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".gradle", ".idea",
                        ".vscode", "bower_components", ".terraform", ".cache", ".phantomkit"}
IGNORE_FILES = (".phantomkitignore", ".semgrepignore")
SUPPRESS_RX = re.compile(r"(?:#|//|/\*|--|<!--|;|%)\s*(nosem(?:grep)?|phantom-ignore|pragma:\s*allowlist\s+secret)\b(.*)$", re.I)
MAX_FINDINGS_PER_RULE_FILE = 500


class ScanError(Exception):
    pass


# ---- ignore handling -------------------------------------------------------
class IgnoreSet:
    def __init__(self):
        self.items = []  # (regex, negate, dir_only, base)

    def add_lines(self, lines, base=""):
        for ln in lines:
            ln = ln.rstrip("\n").rstrip()
            if not ln or ln.startswith("#"):
                continue
            neg = ln.startswith("!")
            if neg:
                ln = ln[1:]
            dir_only = ln.endswith("/")
            anchored = "/" in ln.rstrip("/")
            pat = ln.lstrip("/")
            rx = R._glob_rx(pat if anchored else "**/" + pat)
            self.items.append((rx, neg, dir_only, base))

    def add_file(self, path, base=""):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.add_lines(fh.readlines(), base)
        except OSError:
            pass

    def ignored(self, rel, is_dir=False):
        res = False
        for rx, neg, dir_only, base in self.items:
            if dir_only and not is_dir:
                # a dir pattern also ignores everything beneath it
                target = rel
                parts = rel.split("/")
                hit = any(rx.match("/".join(parts[:i])) for i in range(1, len(parts)))
                if hit:
                    res = not neg
                continue
            r = rel
            if base:
                if not rel.startswith(base + "/"):
                    continue
                r = rel[len(base) + 1:]
            if rx.match(r):
                res = not neg
        return res


def _is_binary(data):
    return b"\x00" in data[:8192]


def _looks_minified(text):
    if len(text) < 2000:
        return False
    lines = text.count("\n") + 1
    return len(text) / lines > 400


def discover(paths, root, cfg_scan, use_gitignore=True, extra_exclude=(), include_hidden_ok=True):
    """Yield (abs_path, rel_path). Files named explicitly are always scanned."""
    ign = IgnoreSet()
    for name in IGNORE_FILES + ((".gitignore",) if use_gitignore else ()):
        ign.add_file(os.path.join(root, name))
    ign.add_lines(list(cfg_scan.get("exclude") or []) + list(extra_exclude))
    include = list(cfg_scan.get("include") or [])
    seen = set()
    for p in paths:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            rel = os.path.relpath(ap, root).replace(os.sep, "/")
            if ap not in seen:
                seen.add(ap)
                yield ap, rel
            continue
        if not os.path.isdir(ap):
            raise ScanError("path not found: %s" % p)
        for dirpath, dirnames, filenames in os.walk(ap, followlinks=False):
            reld = os.path.relpath(dirpath, root).replace(os.sep, "/")
            if reld == ".":
                reld = ""
            keep = []
            for d in sorted(dirnames):
                if d in DEFAULT_EXCLUDE_DIRS:
                    continue
                relp = (reld + "/" + d) if reld else d
                if ign.ignored(relp, True):
                    continue
                keep.append(d)
            dirnames[:] = keep
            for f in sorted(filenames):
                relp = (reld + "/" + f) if reld else f
                full = os.path.join(dirpath, f)
                if os.path.islink(full) or full in seen:
                    continue
                if ign.ignored(relp):
                    continue
                if include and not any(R.path_glob(relp, g) for g in include):
                    continue
                seen.add(full)
                yield full, relp


# ---- suppression -----------------------------------------------------------
def parse_suppressions(lines):
    sup = {}
    for i, ln in enumerate(lines, 1):
        if "nosem" not in ln and "phantom-ignore" not in ln and "allowlist" not in ln:
            continue
        m = SUPPRESS_RX.search(ln)
        if not m:
            continue
        kind = m.group(1).lower()
        rest = m.group(2).strip()
        rest = re.sub(r"(\*/|-->)\s*$", "", rest).strip()
        ids = None
        reason = None
        if kind.startswith("pragma"):
            sup[i] = (["secrets.*"], "allowlist")
            continue
        mm = re.match(r"^[:=]\s*(.*)$", rest)
        if mm:
            parts = re.split(r"\s+(?:--|because|reason:)\s*", mm.group(1), maxsplit=1)
            ids = [x.strip() for x in parts[0].split(",") if x.strip()] or None
            reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        else:
            mr = re.match(r"^(?:--|because|reason:)\s*(.+)$", rest)
            if mr:
                reason = mr.group(1).strip()
        sup[i] = (ids, reason)
    return sup


def _id_matches(ids, rule_id):
    if ids is None:
        return True
    for x in ids:
        if x == rule_id or rule_id.endswith("." + x) or (x.endswith("*") and rule_id.startswith(x[:-1])):
            return True
    return False


def apply_suppression(findings, lines, require_reason=False):
    sup = parse_suppressions(lines)
    if not sup:
        return findings
    for f in findings:
        for ln in (f.line, f.line - 1):
            if ln not in sup:
                continue
            if ln == f.line - 1:
                stripped = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
                if not stripped.startswith(("#", "//", "/*", "--", "<!--", ";", "%")):
                    continue
            ids, reason = sup[ln]
            if not _id_matches(ids, f.rule_id):
                continue
            if require_reason and not reason:
                f.metadata = dict(f.metadata, suppression_ignored="suppression requires a reason (-- why)")
                continue
            f.suppressed = True
            f.suppress_reason = reason
            break
    return findings


# ---- worker ----------------------------------------------------------------
_W = {}


def _init_worker(rule_paths, opts):
    _W["rules"] = R.load_paths(rule_paths) if rule_paths else []
    _W["opts"] = opts


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def scan_one(args):
    full, rel = args
    opts = _W["opts"]
    rules = _W["rules"]
    out = {"rel": rel, "findings": [], "errors": [], "skipped": None, "lang": None}
    try:
        st = os.stat(full)
        if st.st_size > opts["max_size"]:
            out["skipped"] = "too-large"
            return out
        with open(full, "rb") as fh:
            data = fh.read()
    except OSError as ex:
        out["errors"].append({"path": rel, "error": str(ex)})
        return out
    if _is_binary(data):
        out["skipped"] = "binary"
        return out
    text = data.decode("utf-8", errors="replace")
    head = text[:200]
    language = L.detect(rel, head)
    out["lang"] = language
    if "phantom-ignore-file" in text[:500]:
        out["skipped"] = "ignored-file"
        return out
    if language in ("javascript", "typescript") and _looks_minified(text):
        out["skipped"] = "minified"
        return out
    tmo = opts.get("timeout") or 0
    use_alarm = tmo > 0 and hasattr(signal, "SIGALRM") and _main_thread()
    if use_alarm:
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, tmo)
    findings = []
    try:
        applicable = [r for r in rules if r.applies_to_path(rel) and L.lang_matches(r.languages, language)]
        if applicable:
            ctx = M.FileCtx(text, language or "generic", budget=opts.get("budget", 400000))
            eng = Engine(ctx, rel)
            for r in applicable:
                ctx.steps = 0
                try:
                    fs = run_rule(r, eng, ctx, rel)
                except M.MatchBudget:
                    out["errors"].append({"path": rel, "rule": r.id, "error": "pattern-match budget exceeded (rule skipped for this file)"})
                    continue
                except _Timeout:
                    raise
                except Exception as ex:  # a faulty rule must not abort the scan
                    out["errors"].append({"path": rel, "rule": r.id, "error": "%s: %s" % (type(ex).__name__, ex)})
                    continue
                if len(fs) > MAX_FINDINGS_PER_RULE_FILE:
                    out["errors"].append({"path": rel, "rule": r.id, "error": "truncated to %d findings" % MAX_FINDINGS_PER_RULE_FILE})
                    fs = fs[:MAX_FINDINGS_PER_RULE_FILE]
                findings.extend(fs)
        if opts.get("secrets", True) and S.should_scan(rel) and not any(R.path_glob(rel, g) for g in opts.get("secrets_allow_paths", [])):
            findings.extend(S.scan_text(text, rel, allow_regex=opts.get("secrets_allow_regex", ()), disabled=opts.get("secrets_disable", ())))
    except _Timeout:
        out["errors"].append({"path": rel, "error": "timeout after %ss (file partially scanned)" % tmo})
    finally:
        if use_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
    lines = text.split("\n")
    apply_suppression(findings, lines, opts.get("require_reason", False))
    out["findings"] = findings
    return out


def _main_thread():
    import threading
    return threading.current_thread() is threading.main_thread()


# ---- driver ------------------------------------------------------------------
class ScanResult:
    def __init__(self):
        self.findings = []
        self.suppressed = []
        self.baselined = []
        self.errors = []
        self.skipped = {}
        self.files = 0
        self.langs = {}
        self.rules = 0
        self.elapsed = 0.0


def fingerprint(f, occurrence):
    if f.kind == "secret":
        basis = f.metadata.get("secret_sha256_12", "")
    else:
        basis = re.sub(r"\s+", " ", f.snippet or "").strip()
    h = hashlib.sha256()
    h.update(("%s\0%s\0%s\0%d" % (f.rule_id, f.path, basis, occurrence)).encode("utf-8", "replace"))
    return h.hexdigest()[:32]


def assign_fingerprints(findings):
    counts = {}
    for f in findings:
        key = (f.rule_id, f.path, re.sub(r"\s+", " ", f.snippet or "").strip() if f.kind != "secret" else f.metadata.get("secret_sha256_12"))
        n = counts.get(key, 0)
        counts[key] = n + 1
        f.fingerprint = fingerprint(f, n)


def git_changed(root, base):
    def run(*a):
        r = subprocess.run(("git",) + a, cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            raise ScanError("git %s failed: %s" % (" ".join(a), r.stderr.strip()))
        return r.stdout
    files = set(run("diff", "--name-only", "--diff-filter=ACMR", base).split("\n"))
    files |= set(run("ls-files", "--others", "--exclude-standard").split("\n"))
    return {f for f in files if f}


def git_changed_lines(root, base, rel):
    r = subprocess.run(["git", "diff", "-U0", base, "--", rel], cwd=root, capture_output=True, text=True)
    lines = set()
    if r.returncode != 0:
        return None
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", r.stdout, re.M):
        start = int(m.group(1))
        cnt = int(m.group(2)) if m.group(2) is not None else 1
        if cnt == 0:
            continue
        lines.update(range(start, start + cnt))
    if not r.stdout:
        return None  # untracked/new file: everything counts
    return lines


def load_baseline(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return set()
    except ValueError as ex:
        raise ScanError("baseline %s is not valid JSON: %s" % (path, ex))
    return set(data.get("fingerprints", []))


def save_baseline(path, findings):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fps = sorted({f.fingerprint for f in findings})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "count": len(fps), "fingerprints": fps}, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def scan(paths, cfg, rule_paths, root=None, jobs=0, diff_base=None, diff_lines=False, baseline=None, rule_filter=None,
         min_severity=None, secrets=None, progress=None, use_gitignore=True, extra_exclude=()):
    t0 = time.time()
    sc = cfg["scan"]
    root = os.path.abspath(root or os.getcwd())
    res = ScanResult()
    rules = R.load_paths(rule_paths)
    if rule_filter:
        rules = [r for r in rules if rule_filter(r)]
    disabled = set(sc.get("disable-rules") or [])
    if disabled:
        rules = [r for r in rules if r.id not in disabled]
    res.rules = len(rules)
    files = list(discover(paths, root, sc, use_gitignore, extra_exclude))
    if diff_base:
        changed = git_changed(root, diff_base)
        files = [(a, r) for a, r in files if r in changed]
    sec = sc["secrets"]["enabled"] if secrets is None else secrets
    opts = {"max_size": int(sc["max-file-size"]), "timeout": int(sc["timeout"]), "secrets": sec,
            "secrets_allow_paths": sc["secrets"].get("allow-paths", []), "secrets_allow_regex": sc["secrets"].get("allow-regex", []),
            "secrets_disable": sc["secrets"].get("disable", []), "require_reason": bool(sc.get("require-suppress-reason"))}
    rule_files = _rule_files(rule_paths)
    jobs = jobs or int(sc.get("jobs") or 0) or min(os.cpu_count() or 1, 8)
    results = []
    if jobs <= 1 or len(files) < 16:
        _init_worker_from_rules(rules, opts)
        for i, f in enumerate(files):
            results.append(scan_one(f))
            if progress:
                progress(i + 1, len(files))
    else:
        try:
            ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
            with ctx.Pool(jobs, initializer=_init_worker_from_rules if ctx.get_start_method() == "fork" else _init_worker,
                          initargs=(rules, opts) if ctx.get_start_method() == "fork" else (rule_files, opts)) as pool:
                for i, r in enumerate(pool.imap(scan_one, files, chunksize=max(1, len(files) // (jobs * 8)))):
                    results.append(r)
                    if progress:
                        progress(i + 1, len(files))
        except (OSError, ValueError, mp.ProcessError):
            _init_worker_from_rules(rules, opts)
            results = [scan_one(f) for f in files]
    allf = []
    for r in results:
        res.files += 1
        if r["skipped"]:
            res.skipped[r["skipped"]] = res.skipped.get(r["skipped"], 0) + 1
        elif r["lang"]:
            res.langs[r["lang"]] = res.langs.get(r["lang"], 0) + 1
        res.errors.extend(r["errors"])
        allf.extend(r["findings"])
    allf.sort(key=lambda f: (f.path, f.line, f.col, f.rule_id))
    assign_fingerprints(allf)
    if min_severity:
        ms = R.sev_rank(min_severity)
        allf = [f for f in allf if R.sev_rank(f.severity) >= ms]
    if diff_base and diff_lines:
        cache = {}
        keep = []
        for f in allf:
            if f.path not in cache:
                cache[f.path] = git_changed_lines(root, diff_base, f.path)
            ls = cache[f.path]
            if ls is None or any(l in ls for l in range(f.line, f.end_line + 1)):
                keep.append(f)
        allf = keep
    bl = load_baseline(baseline) if baseline else set()
    for f in allf:
        if f.suppressed:
            res.suppressed.append(f)
        elif f.fingerprint in bl:
            res.baselined.append(f)
        else:
            res.findings.append(f)
    res.elapsed = time.time() - t0
    return res


def _init_worker_from_rules(rules, opts):
    _W["rules"] = rules
    _W["opts"] = opts


def _rule_files(rule_paths):
    out = []
    for p in rule_paths:
        if os.path.isdir(p):
            for rt, ds, fs in os.walk(p):
                ds.sort()
                for f in sorted(fs):
                    if f.endswith((".yml", ".yaml")) and not f.endswith((".test.yml", ".test.yaml", ".fixed.yml", ".fixed.yaml")):
                        out.append(os.path.join(rt, f))
        else:
            out.append(p)
    return out
