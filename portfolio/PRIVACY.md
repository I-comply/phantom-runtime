# Privacy

What the portfolio collects and why (mirrors the public `/privacy/` page).

- **Inquiry form:** name, email, optional organization, asset of interest, interest type, message, and a consent flag (not stored beyond being required). Purpose: reply to the inquiry. Stored in a server-side JSONL file with owner-only permissions. Do not collect payment details or confidential documents through it.
- **IP addresses:** used transiently in memory for rate limiting; never written with inquiries or to logs.
- **Counters:** anonymous event names (e.g. `cta_click:PWX-ASSET-000001`) aggregated in a JSON file. No identifiers, no cookies. Requests from browsers with Do Not Track are not sent.
- **Retention and deletion:** keep inquiries only as long as needed; delete on request by editing the JSONL file. The owner must set a retention period before launch.
- **Controller / contact:** Daniel Ron Stevens, drs.vault@proton.me.

This is an engineering description, not legal advice; have the notice reviewed for the jurisdictions you operate in.
