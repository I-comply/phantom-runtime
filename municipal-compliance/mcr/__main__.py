from __future__ import annotations

import argparse
import json
import sys

from .analyze import anthropic_llm
from .models import Source
from .pipeline import run
from .scrape import SnapshotStore
from .submit import FileSink, WebhookSink


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mcr")
    ap.add_argument("--sources", required=True, help="JSON list of {id,jurisdiction,url,selector?}")
    ap.add_argument("--state", default=".mcr/state")
    ap.add_argument("--out", default=".mcr/alerts.jsonl")
    ap.add_argument("--webhook", help="https URL; overrides --out")
    ap.add_argument("--webhook-token")
    ap.add_argument("--min-confidence", type=float, default=0.7)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sources = [Source(**s) for s in json.load(open(a.sources))]
    sink = WebhookSink(a.webhook, a.webhook_token) if a.webhook else FileSink(a.out)
    rep = run(sources, SnapshotStore(a.state), anthropic_llm(), sink,
              min_confidence=a.min_confidence, dry_run=a.dry_run)
    print(json.dumps(rep.__dict__, indent=1))
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
