"""Tool for LLM agents: signs and sends one request to the ATL gateway.
python3 harness/llm_cli.py --url U --tenant T --agent A --secret S ACTION '{"json":"params"}'"""
import argparse, json, sys, urllib.error, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.client import sign_request

p = argparse.ArgumentParser()
for k in ("url", "tenant", "agent", "secret"):
    p.add_argument("--" + k, required=True)
p.add_argument("--key-version", type=int, default=1)
p.add_argument("action"); p.add_argument("params", nargs="?", default="{}")
a = p.parse_args()
req = sign_request(a.secret, a.tenant, a.agent, a.key_version, a.action, json.loads(a.params))
r = urllib.request.Request(a.url + "/v1/invoke", json.dumps(req).encode(), {"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(r, timeout=30) as f:
        print(f.status, f.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
