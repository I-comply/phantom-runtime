"""Deterministic serialization: canonicalization id ``ctal-cjson-1``.

A strict subset of RFC 8785 (JCS): objects, arrays, strings, booleans, null and
integers only (|n| <= 2**53-1). Floats are rejected (ambiguous number
representation). Strings must be valid UTF-8 and already NFC-normalized;
object keys are sorted by UTF-16 code units; no insignificant whitespace;
duplicate keys are rejected on parse. Anything else raises ``CanonError``
*before* any signature is computed or checked.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

CANONICALIZATION_ID = "ctal-cjson-1"
MAX_DEPTH = 32
MAX_BYTES = 1_048_576
MAX_INT = 2 ** 53 - 1


class CanonError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _check_str(s: str) -> None:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise CanonError("LONE_SURROGATE")
    if unicodedata.normalize("NFC", s) != s:
        raise CanonError("NON_NFC_STRING")


def _enc(o: Any, depth: int) -> str:
    if depth > MAX_DEPTH:
        raise CanonError("TOO_DEEP")
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, int):
        if abs(o) > MAX_INT:
            raise CanonError("INT_OUT_OF_RANGE")
        return str(o)
    if isinstance(o, float):
        raise CanonError("FLOAT_NOT_ALLOWED")
    if isinstance(o, str):
        _check_str(o)
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_enc(v, depth + 1) for v in o) + "]"
    if isinstance(o, dict):
        for k in o:
            if not isinstance(k, str):
                raise CanonError("NON_STRING_KEY")
            _check_str(k)
        keys = sorted(o, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _enc(o[k], depth + 1) for k in keys) + "}"
    raise CanonError("UNSUPPORTED_TYPE")


def canonical_bytes(obj: Any) -> bytes:
    out = _enc(obj, 0).encode("utf-8")
    if len(out) > MAX_BYTES:
        raise CanonError("TOO_LARGE")
    return out


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise CanonError("DUPLICATE_KEY")
        d[k] = v
    return d


def _reject(_x):
    raise CanonError("FLOAT_NOT_ALLOWED")


def parse_strict(data, max_bytes: int = MAX_BYTES) -> Any:
    """Parse JSON rejecting duplicates, floats, NaN/Infinity, BOM, oversize, deep nesting."""
    if isinstance(data, str):
        data = data.encode("utf-8", "strict")
    if len(data) > max_bytes:
        raise CanonError("TOO_LARGE")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise CanonError("INVALID_UTF8")
    if text.startswith("﻿"):
        raise CanonError("BOM_NOT_ALLOWED")
    try:
        obj = json.loads(text, object_pairs_hook=_no_dupes, parse_float=_reject, parse_constant=_reject)
    except CanonError:
        raise
    except RecursionError:
        raise CanonError("TOO_DEEP")
    except ValueError:
        raise CanonError("MALFORMED_JSON")
    _enc(obj, 0)  # enforces depth / type / string / int rules
    return obj


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def digest_obj(obj: Any) -> str:
    return sha256_hex(canonical_bytes(obj))
