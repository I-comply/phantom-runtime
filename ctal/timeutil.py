"""Strict UTC timestamps: ``YYYY-MM-DDTHH:MM:SSZ`` only."""
from __future__ import annotations

import re
from datetime import datetime, timezone

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def parse_ts(s: str) -> datetime:
    if not isinstance(s, str) or not _TS.match(s):
        raise ValueError("BAD_TIMESTAMP")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
