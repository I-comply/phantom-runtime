from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import Alert


class Sink(Protocol):
    def submit(self, alert: Alert) -> None: ...


class FileSink:
    """Append-only JSONL; idempotent on alert key."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _seen(self) -> set[str]:
        if not self.path.exists():
            return set()
        return {json.loads(l)["idempotency_key"] for l in self.path.read_text().splitlines() if l.strip()}

    def submit(self, alert: Alert) -> None:
        if alert.idempotency_key in self._seen():
            return
        with self.path.open("a") as f:
            f.write(json.dumps(alert.to_dict(), sort_keys=True) + "\n")


class WebhookSink:
    def __init__(self, url: str, token: str | None = None, attempts: int = 4) -> None:
        if not url.startswith("https://"):
            raise ValueError("webhook must be https")
        self.url, self.token, self.attempts = url, token, attempts

    def submit(self, alert: Alert) -> None:
        headers = {"content-type": "application/json", "idempotency-key": alert.idempotency_key}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        body = json.dumps(alert.to_dict()).encode()
        for i in range(self.attempts):
            try:
                with urllib.request.urlopen(  # noqa: S310
                    urllib.request.Request(self.url, body, headers), timeout=30
                ):
                    return
            except Exception:
                if i == self.attempts - 1:
                    raise
                time.sleep(2**i)
