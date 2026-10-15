from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .analyze import LLM, analyze
from .diff import diff_snapshots
from .models import Source
from .patch import build_alert
from .scrape import Fetcher, SnapshotStore, http_fetch, scrape
from .submit import Sink


@dataclass
class Report:
    submitted: int = 0
    low_confidence: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    baselined: list[str] = field(default_factory=list)


def run(
    sources: list[Source],
    store: SnapshotStore,
    llm: LLM,
    sink: Sink,
    fetch: Fetcher = http_fetch,
    min_confidence: float = 0.7,
    dry_run: bool = False,
) -> Report:
    rep = Report()
    now = datetime.now(timezone.utc).isoformat()
    for src in sources:
        try:
            new = scrape(src, fetch)
            old = store.load(src.id)
            if old is None:
                if not dry_run:
                    store.save(new)
                rep.baselined.append(src.id)
                continue
            if old.sha256 == new.sha256:
                continue
            all_ok = True
            for ch in diff_snapshots(old, new):
                try:
                    f = analyze(ch, llm)
                    if f.confidence < min_confidence:
                        rep.low_confidence.append(f"{src.id}:{ch.section}")
                        all_ok = False  # retry next run rather than lose the change
                        continue
                    if not dry_run:
                        sink.submit(build_alert(src, f, new.sha256, now))
                    rep.submitted += 1
                except Exception as e:  # isolate per section
                    all_ok = False
                    rep.errors.append(f"{src.id}:{ch.section}: {e}")
            if all_ok and not dry_run:
                store.save(new)  # advance baseline only when every change was handled
        except Exception as e:  # isolate per source
            rep.errors.append(f"{src.id}: {e}")
    return rep
