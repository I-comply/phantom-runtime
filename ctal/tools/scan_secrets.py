#!/usr/bin/env python3
"""Minimal secret-pattern scanner for the CTAL tree, fixtures and exports (AT-14).

Not a replacement for a full scanner (gitleaks/trufflehog); it exists so CI has a
dependency-free check for private key material and API-key-shaped strings.
Usage: scan_secrets.py PATH [PATH...]   (files, dirs, or .zip archives). Exit 1 on findings.
"""
import os
import re
import sys
import zipfile

PATTERNS = {
    "private_key_block": re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "ctal_api_key": re.compile(rb"ctal_[A-Za-z0-9_-]{30,}"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "generic_bearer_literal": re.compile(rb"Bearer\s+[A-Za-z0-9_\-.=]{32,}"),
}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SKIP_FILES = {"scan_secrets.py", "test_hygiene.py"}  # contain the patterns/negative fixtures themselves


def scan_bytes(name, data, out):
    for label, rx in PATTERNS.items():
        if rx.search(data):
            out.append((name, label))


def scan_path(p, out):
    if os.path.isdir(p):
        for d, dirs, files in os.walk(p):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                if f not in SKIP_FILES:
                    scan_path(os.path.join(d, f), out)
    elif p.endswith(".zip"):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                scan_bytes(p + "!" + n, z.read(n), out)
    else:
        with open(p, "rb") as f:
            scan_bytes(p, f.read(), out)


def main(argv):
    out = []
    for p in argv[1:]:
        scan_path(p, out)
    for name, label in out:
        print("FINDING %s: %s" % (label, name))
    print("%d finding(s)" % len(out))
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
