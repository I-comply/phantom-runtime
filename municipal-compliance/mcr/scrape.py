from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .models import Snapshot, Source

Fetcher = Callable[[str], str]
SECTION_RE = re.compile(r"^(?:Sec(?:tion)?\.?\s*)?(\d+(?:[.-]\d+)+)\b[\s.:-]*(.*)$", re.I)


def http_fetch(url: str, timeout: float = 30.0) -> str:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"unsupported URL scheme: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mcr-compliance-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (scheme checked)
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "section"}
    SKIP = {"script", "style", "noscript", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        t = " ".join("".join(self._buf).split())
        if t:
            self.lines.append(t)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)


def html_to_lines(html: str) -> list[str]:
    p = _Text()
    p.feed(html)
    p._flush()
    return p.lines


def split_sections(lines: list[str]) -> dict[str, str]:
    """Group lines under the most recent code-section heading (e.g. '12.4.030')."""
    sections: dict[str, list[str]] = {}
    current = "preamble"
    for line in lines:
        m = SECTION_RE.match(line)
        if m and len(line) < 200:
            current = m.group(1)
            sections.setdefault(current, []).append(line)
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def scrape(source: Source, fetch: Fetcher = http_fetch, now: datetime | None = None) -> Snapshot:
    html = fetch(source.url)
    if source.selector:
        start, _, end = source.selector.partition("|")
        i = html.find(start)
        if i < 0:
            raise ValueError(f"{source.id}: start marker not found; page layout changed")
        j = html.find(end, i + len(start)) if end else -1
        html = html[i : j if j > 0 else None]
    sections = split_sections(html_to_lines(html))
    if not sections or sections == {"preamble": ""}:
        raise ValueError(f"{source.id}: no content extracted")
    digest = hashlib.sha256(json.dumps(sections, sort_keys=True).encode()).hexdigest()
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return Snapshot(source.id, ts, digest, sections)


class SnapshotStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, source_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", source_id)
        return self.root / f"{safe}.json"

    def load(self, source_id: str) -> Snapshot | None:
        p = self._path(source_id)
        if not p.exists():
            return None
        return Snapshot(**json.loads(p.read_text()))

    def save(self, snap: Snapshot) -> None:
        p = self._path(snap.source_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap.__dict__, indent=1, sort_keys=True))
        tmp.replace(p)
