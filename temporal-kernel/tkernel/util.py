import hashlib, hmac, json, time


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


def mac(key, h):
    return hmac.new(key, h.encode(), hashlib.sha256).hexdigest()


def now_ms():
    return int(time.time() * 1000)
