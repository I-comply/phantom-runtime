# Integration of the supplied AQPD.js and CLES.js

Source: `AQPD_CLES_Two_Implementations.zip` (2 files, 116 lines). Stored byte-identical in `ctal/adapters/js/` (verified with `cmp`). Wired in through `ctal/adapters/node_bridge.py` + `ctal/adapters/js/bridge.mjs`; enable with `CTAL_ENGINE=js` (see `ctal/config.py`).

## What is and is not established
| Item | Status |
|---|---|
| AQPD.js and CLES.js executed through CTAL, 14 tests incl. end-to-end gate + offline export | PROVEN (Node v22.22.0, Python 3.13.16) |
| Provenance: that these two files are the production AQPD/CLES | UNVERIFIED (supplied without history, tests or docs) |
| `crypto.js` (imported by both files) | **Missing from the archive.** `ctal/adapters/js/crypto.js` is a NEW reconstruction (Ed25519, sorted-key JSON). Compatibility with signatures made by the original system is **UNVERIFIED / BLOCKED** until the original `crypto.js` is supplied |
| Detection accuracy of AQPD rules | UNTESTED; no claim (4 regex rules, trivially evadable by paraphrase) |

## Status mapping
AQPD: `allow→ACCEPT`, `review→REVIEW`, `deny→REJECT`; any other decision→`UNKNOWN`; bridge failure/timeout/unverifiable assessment/digest mismatch→`ERROR`. AQPD.js never emits WARN or QUARANTINE. Single high-severity match (score 55) lands in `review`, two matches or one critical in `deny`. The adapter verifies each assessment signature (`verifyAssessment`) and the content digest before use. Policy-controlled: `max_bytes`, `review_threshold`, `deny_threshold` (validated); rules are fixed in AQPD.js (`aqpd-policy-1.0.0`), CTAL's policy id/version label the decision.

CLES: tenant→license `subject`. `LICENSE_VALID→AUTHORIZED`; `UNKNOWN_ISSUER_KEY`/`INVALID_LICENSE_SIGNATURE→INVALID_SIGNATURE`; `LICENSE_REVOKED→REVOKED`; `LICENSE_NOT_CURRENT→EXPIRED` (expiresAt ≤ now, from signature-verified fields) or `DENIED`; scope/issuer/schema mismatches→`DENIED`; unknown codes→`UNKNOWN`; bridge failure→`ERROR`. Keys marked `revoked` in CTAL config are withheld from CLES.js; `retired` still verify.

## Findings in the supplied code (not modified; mitigated in the adapter where noted)
1. **CLES.verify fails open on omitted scope arguments**: each of `subject/product/deployment/feature` is checked only if provided. Mitigated: bridge rejects requests missing any of them (tested).
2. **`maxActivations` is never enforced** (no activation counter). Not mitigated; a license can be used any number of times (test documents it). SPECIFIED work.
3. **AQPD.js runs every regex over the full input even after flagging `INPUT_TOO_LARGE`.** Mitigated: adapter rejects over `max_bytes` (≤262,144) before calling.
4. **Invalid UTF-8 is silently replaced** before matching. Mitigated: adapter rejects it.
5. `LICENSE_NOT_CURRENT` conflates expired and not-yet-valid. Mitigated in mapping.
6. Revocations are an in-memory Set with no persistence/feed; keys have no status/validity metadata. Mitigated: adapter supplies a revocation list per call and key statuses from CTAL config. Live revocation service remains BLOCKED.
7. Signature scope/canonicalization lives in the missing `crypto.js`; cannot be reviewed.
8. `AQPD.assess` requires `source`; CTAL passes the fixed label `ctal-gate` (a missing source adds 25 points → review).

## Operational notes
Each call spawns Node (hard timeout 5 s, process killed, 1 MB output cap, only `PATH` in the environment); expect tens of milliseconds of overhead. Private AQPD signing key is read from a PEM path by the Node process; keep it 0600 and outside the repository. CI installs Node 22 and sets `CTAL_REQUIRE_NODE=1` so missing Node fails instead of skipping.

## To fully unblock
Supply the original `crypto.js` (and ideally the originals' tests and any sample issued licenses/assessments); re-run `ctal/tests/test_js_adapters.py` against it and against real license fixtures.
