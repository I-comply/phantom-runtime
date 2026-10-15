# Security

## Reporting
Email the owner at drs.vault@proton.me with details. No response-time guarantee is made.

## Controls implemented (see tests/)
- Deny-by-default public projection of asset records; build-time leak guard (forbidden markers, phone number).
- Server serves only `dist/`; traversal, dotfiles, manifest and `/private/*` return 404.
- CSP without inline scripts, frame-ancestors none, nosniff, no-referrer, permissions policy, optional HSTS.
- Inquiry endpoint: JSON only, 16 KB cap, field validation, control-character stripping, honeypot, per-address rate limit, owner-only storage file, no personal data in logs.
- No cookies, no third-party scripts; first-party anonymous counters with an allowlist of event names.

## Not implemented / limits
- No authenticated private diligence area (intentionally; share diligence out-of-band under NDA).
- Rate limiting is per process and in memory; run one instance or add a shared limiter.
- No CAPTCHA; no email delivery; no malware scanning of uploads (there are no uploads).
- Automated scans only: pattern-based secret scan of source repos; no manual security review or penetration test of the portfolio or the marketed assets.
- Dependency audit: the portfolio has no runtime dependencies. Source assets' dependencies were not audited.

Secrets: none are stored in this directory. `.env.example` lists variable names only.
