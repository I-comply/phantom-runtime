"""Rule unit tests: annotate fixtures with `ruleid:` / `ok:` comments (Semgrep-compatible)."""
from __future__ import annotations

import os
import re

from . import rules as R
from . import scanner as S
from . import lang as L
from . import fix as F

ANN = re.compile(r"(?:#|//|/\*|<!--|--|;)\s*(ruleid|ok|todoruleid|todook)\s*:\s*([\w.,\-/ *]+?)\s*(?:\*/|-->)?\s*$", re.I)


def parse_annotations(text):
    """Return ({rule_id: set(lines expected to match)}, {rule_id: set(lines expected clean)})."""
    expect, clean = {}, {}
    lines = text.split("\n")
    for i, ln in enumerate(lines, 1):
        m = ANN.search(ln)
        if not m:
            continue
        kind = m.group(1).lower()
        ids = [x.strip() for x in m.group(2).split(",") if x.strip()]
        # target: next non-annotation line
        j = i + 1
        while j <= len(lines) and ANN.search(lines[j - 1]):
            j += 1
        for rid in ids:
            if kind == "ruleid":
                expect.setdefault(rid, set()).add(j)
            elif kind == "ok":
                clean.setdefault(rid, set()).add(j)
    return expect, clean


def find_fixtures(rule_file):
    base = os.path.splitext(rule_file)[0]
    d = os.path.dirname(rule_file)
    stem = os.path.basename(base)
    out = []
    for f in sorted(os.listdir(d)):
        if f.startswith(stem + ".") and not f.endswith((".yml", ".yaml")) or (f.startswith(stem + ".test.") and f.endswith((".yml", ".yaml"))):
            if ".fixed." in f:
                continue
            out.append(os.path.join(d, f))
    return out


def run(rules_dir, cfg, verbose=False):
    """Return (passed, failed, messages)."""
    msgs = []
    passed = failed = 0
    rule_files = []
    if os.path.isfile(rules_dir):
        rule_files = [rules_dir]
    else:
        for rt, ds, fs in os.walk(rules_dir):
            ds.sort()
            for f in sorted(fs):
                if f.endswith((".yml", ".yaml")) and ".test." not in f and ".fixed." not in f:
                    rule_files.append(os.path.join(rt, f))
    for rf in rule_files:
        try:
            rules = R.load_file(rf)
        except R.RuleError as ex:
            failed += 1
            msgs.append("FAIL %s: %s" % (rf, ex))
            continue
        fixtures = find_fixtures(rf)
        ids = {r.id for r in rules}
        if not fixtures:
            msgs.append("WARN %s: no test fixture (expected %s.<ext>)" % (rf, os.path.splitext(os.path.basename(rf))[0]))
            continue
        for fx in fixtures:
            with open(fx, encoding="utf-8") as fh:
                text = fh.read()
            expect, clean = parse_annotations(text)
            # scan fixture only with this file's rules
            res = S.scan([fx], cfg, [rf], root=os.path.dirname(fx), jobs=1, secrets=False, use_gitignore=False)
            got = {}
            for f in res.findings + res.suppressed:
                got.setdefault(f.rule_id, set()).add(f.line)
            for rid in sorted(ids):
                exp = expect.get(rid, set())
                g = got.get(rid, set())
                miss = exp - g
                extra = g - exp
                bad_clean = clean.get(rid, set()) & g
                label = "%s [%s]" % (os.path.basename(fx), rid)
                if miss or extra or bad_clean:
                    failed += 1
                    if miss:
                        msgs.append("FAIL %s: expected finding on line(s) %s" % (label, sorted(miss)))
                    if extra:
                        msgs.append("FAIL %s: unexpected finding on line(s) %s" % (label, sorted(extra)))
                else:
                    passed += 1
                    if verbose:
                        msgs.append("ok   %s (%d expected)" % (label, len(exp)))
            # autofix check
            base, ext = os.path.splitext(fx)
            fixed = base + ".fixed" + ext
            if os.path.exists(fixed):
                import tempfile, shutil
                with tempfile.TemporaryDirectory() as td:
                    tgt = os.path.join(td, os.path.basename(fx))
                    shutil.copy(fx, tgt)
                    r2 = S.scan([tgt], cfg, [rf], root=td, jobs=1, secrets=False, use_gitignore=False)
                    F.apply(r2.findings, td)
                    with open(tgt, encoding="utf-8") as a, open(fixed, encoding="utf-8") as b:
                        if a.read() == b.read():
                            passed += 1
                        else:
                            failed += 1
                            msgs.append("FAIL %s: autofix output differs from %s" % (os.path.basename(fx), os.path.basename(fixed)))
    return passed, failed, msgs
