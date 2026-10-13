# Pilot runbook, metrics, buyer validation

## Candidate workflow (hypothesis, not validated)
"Content-release gate": a system that publishes or forwards third-party/user/AI-generated content calls `POST /v1/gate` before release; only `PROCEED` releases. Each decision yields a signed envelope and an exportable audit trail. Alternative: software vendor entitlement enforcement with customer-audit evidence. Pick one after buyer conversations.

## Pilot steps
1. Create tenant API keys (gate for the integration, auditor for compliance staff, admin for policy owner). 2. Publish a policy version. 3. Integrate the gate call with `Idempotency-Key = <your event id>` and treat anything except `PROCEED` as stop. 4. Weekly: `GET /v1/export`, verify offline with the pinned key, store the zip. 5. Review `HOLD_FOR_REVIEW` items; record outcomes.

## Metric definitions (compute only from real data; no baselines are fabricated)
| Metric | Definition | Source |
|---|---|---|
| Event→decision latency | `decision.evaluated_at - request time` p50/p95 | request logs + envelopes (timestamps are second-resolution) |
| Coverage | gated events / in-scope workflow events | customer's own workflow count (not available to CTAL) |
| Manual review time | minutes per held case before vs after | customer time study |
| Investigation duration | time from question to evidence located | customer time study using `/v1/events` |
| Decision reliability | non-5xx / total gate calls | request logs |
| Export verification reliability | exports verifying `0` / exports attempted | verifier exit codes |
| Regression catch rate, false positive/negative rate | requires representative labeled ground truth | **not available**; no accuracy claim is made |

## Buyer-validation checklist (all UNTESTED)
- [ ] One buyer segment named · [ ] one recurring workflow observed · [ ] one measurable cost or risk quantified · [ ] budget owner identified and interviewed · [ ] ≥5 real buyer conversations documented with notes · [ ] pilot scope + price agreed in writing · [ ] success metric agreed up front · [ ] paid conversion recorded · [ ] renewal outcome (only when observed).
