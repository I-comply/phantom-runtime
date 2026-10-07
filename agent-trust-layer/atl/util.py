import hashlib, hmac, json, math, re, time

ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def valid_id(x):
    """Ids become path components (sandbox/evidence dirs). '.' and '..' match the character class
    but would escape the directory, so names made only of dots are rejected."""
    return isinstance(x, str) and ID_RE.match(x) is not None and x.strip(".") != ""


def canon(o):
    def chk(v, d=0):
        if d > 16:
            raise ValueError("too_deep")
        if isinstance(v, bool) or v is None or isinstance(v, (str, int)):
            return
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError("non_finite")
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if not isinstance(k, str):
                    raise ValueError("bad_key")
                chk(x, d + 1)
            return
        if isinstance(v, (list, tuple)):
            for x in v:
                chk(x, d + 1)
            return
        raise ValueError("bad_type")
    chk(o)
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def mac(key, msg):
    if isinstance(key, str):
        key = bytes.fromhex(key)
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def eq(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def now_ms():
    return int(time.time() * 1000)


def http_open(req, timeout):
    """urlopen restricted to http/https (no file:/ftp:/custom schemes)."""
    import urllib.request
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("bad_url_scheme")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310
