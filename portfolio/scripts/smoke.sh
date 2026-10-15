#!/usr/bin/env bash
# Post-deploy smoke test. Usage: BASE=https://your-domain bash scripts/smoke.sh   (default http://127.0.0.1:8080)
# Read-only except one deliberately INVALID inquiry (rejected with 422; nothing is stored).
set -u
BASE="${BASE:-http://127.0.0.1:8080}"
fail=0
check() { # name expected_status url [extra curl args]
  local name="$1" want="$2" url="$3"; shift 3
  local got; got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" "$BASE$url")
  if [ "$got" = "$want" ]; then echo "ok   $name ($got)"; else echo "FAIL $name: want $want got $got"; fail=1; fi
}
check healthz 200 /healthz
check home 200 /
check catalog 200 /assets/
check inquiry-page 200 /inquiry/
check robots 200 /robots.txt
check sitemap 200 /sitemap.xml
check assets-json 200 /assets.json
check private-dir 404 /private/assets/PWX-ASSET-000001.json
check traversal 404 "/%2e%2e/package.json"
check manifest-hidden 404 /MANIFEST.sha256.json
check invalid-inquiry 422 /api/inquiry -X POST -H 'content-type: application/json' -d '{"name":"smoke","email":"bad","message":"x","consent":true}'
slug=$(curl -s --max-time 15 "$BASE/assets.json" | python3 -c 'import sys,json; a=json.load(sys.stdin)["assets"]; print(a[0]["slug"] if a else "")' 2>/dev/null)
if [ -n "$slug" ]; then
  check asset-page 200 "/assets/$slug/"
  check demo-page 200 "/demos/$slug/"
  check pitch-deck 200 "/decks/$slug-pitch.html"
else echo "note: catalog is empty (no approved assets); asset-level checks skipped"; fi
hdr=$(curl -sI --max-time 15 "$BASE/")
for h in content-security-policy x-content-type-options referrer-policy; do
  echo "$hdr" | grep -qi "^$h:" && echo "ok   header $h" || { echo "FAIL header $h missing"; fail=1; }
done
exit $fail
