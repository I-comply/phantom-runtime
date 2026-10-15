"""Secret detection: provider patterns, generic assignments, entropy and validators. Output is always redacted."""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .engine import entropy, Finding

PLACEHOLDER = re.compile(
    r"(?i)(change.?me|example|your[_-]|<[^>]+>|\$\{|\{\{|xxxx|\*{4,}|placeholder|dummy|sample|todo|fixme|test(?:ing)?[_-]?(?:key|secret|token)|"
    r"^(?:password|secret|token|none|null|true|false|undefined|string|value|redacted|abc123|12345678?|foobar|hunter2)$|process\.env|os\.environ|getenv|env\()")


def _luhn(num):
    ds = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(ds) <= 19:
        return False
    s = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


def _jwt_check(val, g):
    parts = val.split(".")
    if len(parts) != 3:
        return None
    try:
        def dec(p):
            return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        h = dec(parts[0])
        pl = dec(parts[1])
    except Exception:
        return False
    if not isinstance(h, dict) or "alg" not in h:
        return False
    if isinstance(pl, dict) and pl.get("role") == "service_role":
        return "critical"
    if isinstance(pl, dict) and pl.get("role") == "anon":
        return "public"
    return True


def _cc(val, g):
    d = re.sub(r"[ -]", "", val)
    return d.isdigit() and re.match(r"^(4\d{12}(\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})$", d) is not None and _luhn(d)


# (id, description, regex, severity, group, min_entropy, validator)
RULES = [
    ("aws-access-key-id", "AWS access key ID", r"\b((?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16})\b", "ERROR", 1, 3.0, None),
    ("aws-secret-access-key", "AWS secret access key",
     r"(?i)aws.{0,30}?(?:secret|sk|private).{0,30}?['\"`=:\s]\s*['\"`]?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])", "ERROR", 1, 4.2, None),
    ("github-token", "GitHub token", r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255})\b", "ERROR", 1, 3.5, None),
    ("github-fine-grained-pat", "GitHub fine-grained token", r"\b(github_pat_[A-Za-z0-9_]{70,100})\b", "ERROR", 1, 3.5, None),
    ("gitlab-pat", "GitLab personal access token", r"\b(glpat-[A-Za-z0-9_\-]{20,})\b", "ERROR", 1, 3.0, None),
    ("slack-token", "Slack token", r"\b(xox[baprs]-[0-9A-Za-z\-]{10,72})\b", "ERROR", 1, 3.0, None),
    ("slack-webhook", "Slack webhook URL", r"(https://hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{20,})", "WARNING", 1, 0, None),
    ("stripe-live-key", "Stripe live secret key", r"\b((?:sk|rk)_live_[0-9a-zA-Z]{20,})\b", "ERROR", 1, 3.0, None),
    ("google-api-key", "Google API key", r"\b(AIza[0-9A-Za-z_\-]{35})\b", "WARNING", 1, 3.5, None),
    ("gcp-service-account", "GCP service account private key", r"(\"private_key_id\"\s*:\s*\"[0-9a-f]{40}\")", "ERROR", 1, 0, None),
    ("private-key", "Private key block",
     r"(-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----)", "ERROR", 1, 0, None),
    ("jwt", "JSON Web Token", r"\b(eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})\b", "WARNING", 1, 3.0, _jwt_check),
    ("npm-token", "npm access token", r"\b(npm_[A-Za-z0-9]{36})\b", "ERROR", 1, 3.5, None),
    ("npmrc-auth-token", "npm registry auth token", r"(?m)^\s*//[^\s]+/:_authToken\s*=\s*([^\s$\"']{16,})\s*$", "ERROR", 1, 3.0, None),
    ("pypi-token", "PyPI upload token", r"\b(pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,})\b", "ERROR", 1, 3.5, None),
    ("sendgrid-key", "SendGrid API key", r"\b(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})\b", "ERROR", 1, 3.5, None),
    ("twilio-key", "Twilio API key", r"\b(SK[0-9a-fA-F]{32})\b", "WARNING", 1, 3.0, None),
    ("mailgun-key", "Mailgun API key", r"\b(key-[0-9a-zA-Z]{32})\b", "WARNING", 1, 3.5, None),
    ("digitalocean-token", "DigitalOcean token", r"\b(do[opr]_v1_[a-f0-9]{64})\b", "ERROR", 1, 3.0, None),
    ("shopify-token", "Shopify access token", r"\b(shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32})\b", "ERROR", 1, 3.0, None),
    ("azure-storage-key", "Azure storage account key", r"AccountKey=([A-Za-z0-9+/]{86}==)", "ERROR", 1, 4.0, None),
    ("anthropic-key", "Anthropic API key", r"\b(sk-ant-[A-Za-z0-9_\-]{40,})\b", "ERROR", 1, 3.5, None),
    ("openai-key", "OpenAI API key", r"\b(sk-(?:proj-)?[A-Za-z0-9_\-]{32,}|sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b", "ERROR", 1, 4.0, None),
    ("db-connection-password", "Password embedded in connection URL",
     r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqps?|mssql)://[^:\s/@'\"]+:([^@\s'\"/]{4,})@", "ERROR", 1, 0, None),
    ("url-basic-auth", "Credentials embedded in URL", r"(?i)\bhttps?://[^:\s/@'\"]+:([^@\s'\"/]{4,})@[a-z0-9.\-]+", "WARNING", 1, 2.5, None),
    ("generic-secret-assignment", "Hardcoded credential assignment",
     r"(?i)\b[\w.\-]*(?:password|passwd|pwd|secret|api[_\-]?key|apikey|auth[_\-]?token|access[_\-]?token|private[_\-]?key|client[_\-]?secret)[\w.\-]*\s*[:=]\s*[\"'`]([^\"'`\s]{8,120})[\"'`]",
     "WARNING", 1, 3.0, None),
    ("credit-card-number", "Payment card number (Luhn valid)", r"(?<![\d.])((?:\d[ -]?){13,19})(?![\d])", "WARNING", 1, 0, _cc),
]

SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "npm-shrinkwrap.json"}
SKIP_EXT = (".min.js", ".min.css", ".map", ".svg", ".lock", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf",
            ".eot", ".zip", ".gz", ".tgz", ".jar", ".so", ".dll", ".exe", ".bin", ".pyc", ".class")

_COMPILED = None


def compiled():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [(rid, desc, re.compile(rx), sev, grp, ent, val) for (rid, desc, rx, sev, grp, ent, val) in RULES]
    return _COMPILED


def redact(s):
    s = str(s)
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * min(len(s) - 6, 12) + s[-2:]


def should_scan(path):
    base = path.rsplit("/", 1)[-1]
    if base in SKIP_NAMES or base.endswith(SKIP_EXT):
        return False
    return True


def scan_text(src, path, ctx=None, allow_regex=(), disabled=()):
    """Return Finding list. `ctx` (FileCtx) is optional and only used for line/col math."""
    out = []
    ls = [0]
    i = src.find("\n")
    while i >= 0:
        ls.append(i + 1)
        i = src.find("\n", i + 1)
    import bisect

    def pos(off):
        k = bisect.bisect_right(ls, off) - 1
        return k + 1, off - ls[k] + 1

    allow = [re.compile(a) for a in allow_regex]
    for rid, desc, rx, sev, grp, min_ent, validator in compiled():
        if rid in disabled or ("secrets." + rid) in disabled:
            continue
        for m in rx.finditer(src):
            val = m.group(grp)
            if not val:
                continue
            if rid in ("generic-secret-assignment", "db-connection-password", "url-basic-auth") and PLACEHOLDER.search(val):
                continue
            if rid == "generic-secret-assignment" and re.search(r"(?i)^[a-z_.]+\(|^\w+\.\w+$|^[A-Z_]{4,}$", val):
                continue
            if min_ent and entropy(val) < min_ent:
                continue
            if any(a.search(val) for a in allow):
                continue
            s_sev = sev
            note = None
            if validator is not None:
                v = validator(val, m)
                if v is False or v is None:
                    continue
                if v == "critical":
                    s_sev = "CRITICAL"
                    note = "Supabase service_role key"
                elif v == "public":
                    continue
            line, col = pos(m.start(grp))
            eline, ecol = pos(m.end(grp))
            lstart = ls[line - 1]
            lend = ls[line] - 1 if line < len(ls) else len(src)
            raw_line = src[lstart:lend]
            red = raw_line if rid == "private-key" else raw_line.replace(val, redact(val))
            if len(red) > 200:
                red = red[:200] + "..."
            fp_secret = hashlib.sha256(val.encode()).hexdigest()[:12]
            out.append(Finding(
                rule_id="secrets." + rid, path=path, line=line, col=col, end_line=eline, end_col=ecol, start=m.start(grp), end=m.end(grp),
                message="%s detected%s. Rotate the credential and load it from the environment or a secret manager." % (desc, " (%s)" % note if note else ""),
                severity=s_sev, metadata={"category": "secrets", "confidence": "HIGH" if min_ent == 0 or rid not in ("generic-secret-assignment",) else "MEDIUM",
                                          "cwe": ["CWE-798: Use of Hard-coded Credentials"], "secret_sha256_12": fp_secret},
                snippet=red.strip("\r"), kind="secret", rule_source="builtin:secrets"))
    return out


def rule_list():
    return [{"id": "secrets." + r[0], "description": r[1], "severity": r[3]} for r in RULES]
