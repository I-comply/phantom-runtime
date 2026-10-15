"""Output formats: text, json, sarif, junit, github annotations, markdown."""
from __future__ import annotations

import json
import os
import sys
from xml.sax.saxutils import escape, quoteattr

from . import __version__
from .rules import sev_rank

SARIF_LEVEL = {"INFO": "note", "WARNING": "warning", "ERROR": "error", "CRITICAL": "error"}
SECURITY_SEVERITY = {"INFO": "3.0", "WARNING": "5.5", "ERROR": "8.0", "CRITICAL": "9.5"}


def _color(enabled):
    if not enabled:
        return lambda c, s: s
    codes = {"red": "31", "yellow": "33", "blue": "34", "dim": "2", "bold": "1", "green": "32", "magenta": "35"}
    return lambda c, s: "\x1b[%sm%s\x1b[0m" % (codes[c], s)


def finding_dict(f):
    d = {
        "check_id": f.rule_id,
        "path": f.path,
        "start": {"line": f.line, "col": f.col, "offset": f.start},
        "end": {"line": f.end_line, "col": f.end_col, "offset": f.end},
        "extra": {
            "message": f.message,
            "severity": f.severity,
            "kind": f.kind,
            "metadata": f.metadata,
            "lines": f.snippet,
            "fingerprint": f.fingerprint,
        },
    }
    if f.fix:
        d["extra"]["fix"] = f.fix
    if f.trace:
        d["extra"]["dataflow_trace"] = f.trace
    if f.suppressed:
        d["extra"]["is_ignored"] = True
        if f.suppress_reason:
            d["extra"]["suppress_reason"] = f.suppress_reason
    return d


def to_json(res, include_suppressed=False):
    out = {
        "version": __version__,
        "results": [finding_dict(f) for f in res.findings],
        "errors": res.errors,
        "paths": {"scanned": res.files, "skipped": res.skipped},
        "stats": {"rules": res.rules, "files": res.files, "elapsed_seconds": round(res.elapsed, 3), "languages": res.langs,
                  "suppressed": len(res.suppressed), "baselined": len(res.baselined)},
    }
    if include_suppressed:
        out["suppressed"] = [finding_dict(f) for f in res.suppressed]
        out["baselined"] = [finding_dict(f) for f in res.baselined]
    return json.dumps(out, indent=2, sort_keys=False)


def to_text(res, color=False, show_fix=True, verbose=False):
    c = _color(color)
    lines = []
    by_file = {}
    for f in res.findings:
        by_file.setdefault(f.path, []).append(f)
    for path in sorted(by_file):
        lines.append(c("bold", path))
        for f in by_file[path]:
            sev = {"CRITICAL": "magenta", "ERROR": "red", "WARNING": "yellow", "INFO": "blue"}.get(f.severity, "dim")
            lines.append("  %s %s  %s" % (c(sev, "%-8s" % f.severity), c("dim", "%d:%d" % (f.line, f.col)), c("bold", f.rule_id)))
            for ml in f.message.splitlines():
                lines.append("    " + ml)
            if f.snippet:
                first = f.snippet.splitlines()[0] if f.snippet else ""
                lines.append("    %s | %s" % (c("dim", str(f.line).rjust(4)), first.strip()[:160]))
            if f.trace:
                t = f.trace
                chain = " -> ".join(["source L%d `%s`" % (t["source"]["line"], t["source"]["text"][:50])] + list(t.get("via", [])) +
                                    ["sink L%d" % t["sink"]["line"]])
                lines.append("    " + c("dim", "flow: " + chain))
            if show_fix and f.fix:
                lines.append("    " + c("green", "fix: ") + f.fix.splitlines()[0][:120])
            if f.metadata.get("suppression_ignored"):
                lines.append("    " + c("yellow", f.metadata["suppression_ignored"]))
        lines.append("")
    n = len(res.findings)
    bysev = {}
    for f in res.findings:
        bysev[f.severity] = bysev.get(f.severity, 0) + 1
    summary = "%d finding%s" % (n, "" if n == 1 else "s")
    if bysev:
        summary += " (" + ", ".join("%d %s" % (bysev[s], s.lower()) for s in ("CRITICAL", "ERROR", "WARNING", "INFO") if s in bysev) + ")"
    lines.append(c("bold", summary) + "; %d files, %d rules, %.2fs" % (res.files, res.rules, res.elapsed))
    if res.suppressed or res.baselined:
        lines.append("%d suppressed inline, %d in baseline" % (len(res.suppressed), len(res.baselined)))
    if res.errors:
        lines.append(c("yellow", "%d scan warning(s):" % len(res.errors)))
        for e in res.errors[: (50 if verbose else 5)]:
            lines.append("  %s%s: %s" % (e.get("path", ""), " [%s]" % e["rule"] if e.get("rule") else "", e["error"]))
        if len(res.errors) > 5 and not verbose:
            lines.append("  ... use --verbose to list all")
    return "\n".join(lines) + "\n"


def to_sarif(res, rules, include_suppressed=True):
    rule_idx = {}
    sarif_rules = []
    meta = {r.id: r for r in rules}
    allf = list(res.findings) + (list(res.suppressed) if include_suppressed else [])
    for f in allf:
        if f.rule_id in rule_idx:
            continue
        r = meta.get(f.rule_id)
        md = (r.metadata if r else f.metadata) or {}
        tags = []
        for key in ("cwe", "owasp"):
            v = md.get(key)
            if v:
                tags.extend(v if isinstance(v, list) else [v])
        if md.get("category"):
            tags.append(str(md["category"]))
        entry = {
            "id": f.rule_id,
            "name": f.rule_id.split(".")[-1],
            "shortDescription": {"text": (r.message if r else f.message).splitlines()[0][:200]},
            "fullDescription": {"text": (r.message if r else f.message)[:1000]},
            "defaultConfiguration": {"level": SARIF_LEVEL.get(f.severity, "warning")},
            "properties": {"tags": tags, "precision": str(md.get("confidence", "medium")).lower(),
                           "security-severity": SECURITY_SEVERITY.get(f.severity, "5.5")},
        }
        refs = md.get("references")
        if refs:
            entry["helpUri"] = refs[0] if isinstance(refs, list) else refs
        rule_idx[f.rule_id] = len(sarif_rules)
        sarif_rules.append(entry)
    results = []
    for f in allf:
        loc = {"physicalLocation": {"artifactLocation": {"uri": f.path, "uriBaseId": "%SRCROOT%"},
                                    "region": {"startLine": f.line, "startColumn": f.col, "endLine": f.end_line, "endColumn": f.end_col,
                                               "snippet": {"text": (f.snippet or "")[:500]}}}}
        r = {"ruleId": f.rule_id, "ruleIndex": rule_idx[f.rule_id], "level": SARIF_LEVEL.get(f.severity, "warning"),
             "message": {"text": f.message}, "locations": [loc], "partialFingerprints": {"phantomkit/v1": f.fingerprint}}
        if f.trace:
            t = f.trace
            def tloc(d, text):
                return {"location": {"physicalLocation": {"artifactLocation": {"uri": f.path, "uriBaseId": "%SRCROOT%"},
                                                         "region": {"startLine": d["line"], "startColumn": d["col"]}},
                                     "message": {"text": text}}}
            r["codeFlows"] = [{"threadFlows": [{"locations": [tloc(t["source"], "source: " + t["source"]["text"][:80]),
                                                               tloc(t["sink"], "sink: " + t["sink"]["text"][:80])]}]}]
        if f.fix:
            r["fixes"] = [{"description": {"text": "Apply suggested fix"},
                           "artifactChanges": [{"artifactLocation": {"uri": f.path},
                                                "replacements": [{"deletedRegion": {"startLine": f.line, "startColumn": f.col,
                                                                                    "endLine": f.end_line, "endColumn": f.end_col},
                                                                  "insertedContent": {"text": f.fix}}]}]}]
        if f.suppressed:
            r["suppressions"] = [{"kind": "inSource", "justification": f.suppress_reason or ""}]
        results.append(r)
    doc = {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
           "runs": [{"tool": {"driver": {"name": "phantomkit", "version": __version__, "informationUri": "https://github.com/I-comply/phantom-runtime",
                                         "rules": sarif_rules}},
                     "originalUriBaseIds": {"%SRCROOT%": {"uri": "file://" + os.getcwd().replace(os.sep, "/") + "/"}},
                     "results": results,
                     "invocations": [{"executionSuccessful": True, "toolExecutionNotifications": [
                         {"level": "warning", "message": {"text": e["error"]}} for e in res.errors[:100]]}]}]}
    return json.dumps(doc, indent=2)


def to_junit(res, suite="phantomkit"):
    cases = []
    for f in res.findings:
        cases.append('  <testcase classname=%s name=%s><failure message=%s type=%s>%s</failure></testcase>' % (
            quoteattr(f.path), quoteattr("%s:%d" % (f.rule_id, f.line)), quoteattr(f.message.splitlines()[0][:200]), quoteattr(f.severity),
            escape("%s:%d:%d\n%s" % (f.path, f.line, f.col, f.snippet or ""))))
    if not cases:
        cases.append('  <testcase classname="phantomkit" name="no findings"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name=%s tests="%d" failures="%d" time="%.3f">\n%s\n</testsuite>\n' %
            (quoteattr(suite), max(len(res.findings), 1), len(res.findings), res.elapsed, "\n".join(cases)))


def to_github(res):
    out = []
    for f in res.findings:
        lvl = "error" if sev_rank(f.severity) >= 3 else ("warning" if f.severity == "WARNING" else "notice")
        msg = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        out.append("::%s file=%s,line=%d,col=%d,endLine=%d,endColumn=%d,title=%s::%s" % (
            lvl, f.path, f.line, f.col, f.end_line, f.end_col, f.rule_id, msg))
    return "\n".join(out) + ("\n" if out else "")


def to_markdown(res, title="phantomkit scan"):
    lines = ["### %s" % title, "", "| Severity | Rule | Location | Message |", "|---|---|---|---|"]
    for f in res.findings:
        lines.append("| %s | `%s` | `%s:%d` | %s |" % (f.severity, f.rule_id, f.path, f.line, f.message.splitlines()[0].replace("|", "\\|")[:140]))
    if not res.findings:
        lines.append("| - | - | - | No findings |")
    lines.append("")
    lines.append("%d findings, %d suppressed, %d baselined, %d files, %.1fs" % (len(res.findings), len(res.suppressed), len(res.baselined), res.files, res.elapsed))
    return "\n".join(lines) + "\n"


FORMATS = ("text", "json", "sarif", "junit", "github", "markdown")


def render(fmt, res, rules, color=False, include_suppressed=False, verbose=False):
    if fmt == "text":
        return to_text(res, color, verbose=verbose)
    if fmt == "json":
        return to_json(res, include_suppressed)
    if fmt == "sarif":
        return to_sarif(res, rules)
    if fmt == "junit":
        return to_junit(res)
    if fmt == "github":
        return to_github(res)
    if fmt == "markdown":
        return to_markdown(res)
    raise ValueError("unknown format %s" % fmt)
