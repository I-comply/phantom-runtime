# Standalone sandbox worker. stdlib only. Runs as: python -I worker.py  (cwd = sandbox root)
import hashlib, json, os, sys

MAX = 1 << 20


def limits():
    try:
        import resource
        for r, v in ((resource.RLIMIT_CPU, 5), (resource.RLIMIT_FSIZE, 10 << 20), (resource.RLIMIT_NOFILE, 64),
                     (resource.RLIMIT_AS, 512 << 20)):
            try:
                resource.setrlimit(r, (v, v))
            except (ValueError, OSError):
                pass
    except ImportError:
        pass


def safe(root, p):
    if not isinstance(p, str) or "\x00" in p:
        raise ValueError("bad_path")
    full = os.path.realpath(os.path.join(root, p))
    if os.path.commonpath([root, full]) != root or full == root:
        raise ValueError("path_escape")
    return full


def run(tool, a, root):
    if tool == "echo":
        return {"text": a["text"]}
    if tool == "hash_text":
        return {"sha256": hashlib.sha256(a["text"].encode()).hexdigest()}
    if tool == "fs_read":
        with open(safe(root, a["path"]), "rb") as f:
            d = f.read(MAX + 1)
        if len(d) > MAX:
            raise ValueError("too_large")
        return {"content": d.decode("utf-8", "replace")}
    if tool == "fs_write":
        p = safe(root, a["path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        d = a["content"].encode()
        with open(p, "wb") as f:
            f.write(d)
        return {"path": a["path"], "bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()}
    if tool == "fs_delete":
        p = safe(root, a["path"])
        if not os.path.isfile(p):
            raise ValueError("not_a_file")
        os.remove(p)
        return {"deleted": a["path"]}
    raise ValueError("unknown_tool")


def main():
    limits()
    try:
        req = json.loads(sys.stdin.read())
        out = {"ok": True, "output": run(req["tool"], req["params"], os.path.realpath(os.getcwd()))}
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}:{e}"[:200]}
    sys.stdout.write(json.dumps(out))
    sys.exit(0 if out["ok"] else 1)


main()
