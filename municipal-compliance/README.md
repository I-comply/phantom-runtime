# municipal-compliance

Scrape municipal code pages → diff by section → LLM impact analysis → structured patches + alerts.

```
export ANTHROPIC_API_KEY=...
python -m mcr --sources sources.json [--webhook https://...] [--dry-run]
python -m unittest discover -s tests
```

`sources.json`: `[{"id":"city-a","jurisdiction":"City A","url":"https://...","selector":"<start marker>|<end marker>"}]`

- First run baselines each source (no alerts).
- Alerts are idempotent (`sha256(source|section|content-hash)`), submitted via file (JSONL) or HTTPS webhook with retry.
- Findings below `--min-confidence` or with invalid LLM output are not submitted; the baseline does not advance, so they are retried next run.
- Exit code 1 if any source/section errored.
