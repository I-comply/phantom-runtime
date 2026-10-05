"""Minimal MCP (stdio JSON-RPC) adapter. Every tool call is signed and sent through the ATL gateway."""
import json, os, sys, urllib.request
from .client import sign_request
from .policy import Policy


def _call(url, req):
    r = urllib.request.Request(url + "/v1/invoke", json.dumps(req).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return json.loads(f.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def main():
    t, a = os.environ["ATL_TENANT"], os.environ["ATL_AGENT"]
    ver, sec = int(os.environ.get("ATL_KEY_VERSION", "1")), os.environ["ATL_SECRET"]
    url = os.environ.get("ATL_URL", "http://127.0.0.1:8787")
    pol = Policy.load(os.environ["ATL_MANIFEST"])
    tools = [{"name": n, "description": f"ATL-governed tool (risk={s['risk']})",
              "inputSchema": {"type": "object", "additionalProperties": False,
                              "required": [k for k, p in s.get("params", {}).items() if p.get("required")],
                              "properties": {k: {"type": p["type"]} for k, p in s.get("params", {}).items()}}}
             for n, s in pol.tools.items() if pol.granted(a, n)]
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        mid, meth = m.get("id"), m.get("method")
        if mid is None:
            continue
        if meth == "initialize":
            res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "agent-trust-layer", "version": "0.1.0"}}
        elif meth == "tools/list":
            res = {"tools": tools}
        elif meth == "tools/call":
            p = m.get("params", {})
            out = _call(url, sign_request(sec, t, a, ver, p.get("name", ""), p.get("arguments", {})))
            res = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": not out.get("ok")}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
