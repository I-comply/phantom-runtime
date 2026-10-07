import hashlib, importlib, importlib.util, json, os, sys


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(o):
    return hashlib.sha256(canon(o).encode()).hexdigest()


def norm(o):
    """JSON round trip so tuples/lists and key order compare equal."""
    return json.loads(canon(o))


def first_diff(a, b, path="$"):
    """Path of the first difference between two JSON values, or None."""
    if type(a) != type(b):
        return path
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return "%s.%s" % (path, k)
            d = first_diff(a[k], b[k], "%s.%s" % (path, k))
            if d:
                return d
        return None
    if isinstance(a, list):
        for i in range(min(len(a), len(b))):
            d = first_diff(a[i], b[i], "%s[%d]" % (path, i))
            if d:
                return d
        return None if len(a) == len(b) else "%s[len]" % path
    return None if a == b else path


def load_module(spec):
    """spec is a dotted module name or a path to a .py file."""
    if spec.endswith(".py") or os.path.isfile(spec):
        path = os.path.abspath(spec)
        sys.path.insert(0, os.path.dirname(path))
        name = "rc_user_" + os.path.splitext(os.path.basename(path))[0]
        s = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(s)
        s.loader.exec_module(m)
        return m
    sys.path.insert(0, os.getcwd())
    return importlib.import_module(spec)


def need(mod, *names):
    for n in names:
        if not callable(getattr(mod, n, None)):
            raise SystemExit("error: module %r must define %s()" % (mod.__name__, n))
