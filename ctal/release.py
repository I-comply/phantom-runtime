"""Signed release manifest + SBOM (CycloneDX 1.5 JSON subset).

``release_digest`` equals the ``software_release_digest`` placed in every envelope by a running service built
from the same tree, so a decision can be linked to the exact files that produced it. The manifest is signed with the
export key and verified offline with the same pinned-key procedure. This is a source-tree manifest, not a hermetic
build attestation (no SLSA provenance, no reproducible-build claim).
"""
from __future__ import annotations

import importlib.metadata
import os
import platform
from typing import Dict, List, Tuple

from .canon import canonical_bytes, digest_obj, sha256_hex
from .export import sign_doc
from .keys import ALGORITHM, Signer, TrustStore, VerifyError
from .timeutil import fmt_ts, now_utc

ROOT = os.path.dirname(__file__)


def release_files() -> List[Tuple[str, str]]:
    out = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", "tests"))
        for f in sorted(files):
            if f.endswith((".py", ".sql", ".json", ".js", ".mjs")):
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out.append((os.path.relpath(p, ROOT).replace(os.sep, "/"), sha256_hex(fh.read())))
    return out


def tree_digest() -> str:
    return sha256_hex("\n".join(p + ":" + h for p, h in release_files()).encode())


def sbom() -> dict:
    comps = []
    for dist in ("cryptography",):
        try:
            comps.append({"type": "library", "name": dist, "version": importlib.metadata.version(dist),
                          "purl": "pkg:pypi/%s@%s" % (dist, importlib.metadata.version(dist))})
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": "ctal", "version": "0.2.0"},
                         "properties": [{"name": "python", "value": platform.python_version()}]},
            "components": comps}


def build_manifest(signer: Signer, clock=now_utc) -> dict:
    sb = sbom()
    files = release_files()
    return sign_doc({"schema_version": "ctal.release.v1", "created_at": fmt_ts(clock()),
                     "release_digest": sha256_hex("\n".join(p + ":" + h for p, h in files).encode()),
                     "files": [{"path": p, "sha256": h} for p, h in files],
                     "sbom_digest": digest_obj(sb), "sbom": sb}, signer)


def verify_manifest(doc: dict, trust: TrustStore, check_tree: bool = True) -> Dict[str, object]:
    errs = []
    try:
        sg = doc["signing"]
        if sg.get("algorithm") != ALGORITHM:
            errs.append("ALGORITHM_NOT_ALLOWED")
        else:
            unsigned = dict(doc)
            unsigned["signing"] = {k: v for k, v in sg.items() if k != "signature"}
            trust.verify(sg["key_id"], "export", canonical_bytes(unsigned), sg["signature"])
        if doc["schema_version"] != "ctal.release.v1":
            errs.append("SCHEMA")
        if sha256_hex("\n".join(f["path"] + ":" + f["sha256"] for f in doc["files"]).encode()) != doc["release_digest"]:
            errs.append("RELEASE_DIGEST_MISMATCH")
        if digest_obj(doc["sbom"]) != doc["sbom_digest"]:
            errs.append("SBOM_DIGEST_MISMATCH")
        if check_tree and tree_digest() != doc["release_digest"]:
            errs.append("TREE_DIFFERS_FROM_MANIFEST")
    except VerifyError as e:
        errs.append(e.code)
    except (KeyError, TypeError, ValueError):
        errs.append("MALFORMED")
    return {"ok": not errs, "errors": errs}
