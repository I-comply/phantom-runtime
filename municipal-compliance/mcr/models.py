from __future__ import annotations

from dataclasses import dataclass, field, asdict

SEVERITIES = ("info", "minor", "major", "critical")


@dataclass(frozen=True)
class Source:
    id: str
    jurisdiction: str
    url: str
    selector: str | None = None  # CSS-free: optional start/end markers "start|end"


@dataclass
class Snapshot:
    source_id: str
    fetched_at: str
    sha256: str
    sections: dict[str, str]  # section id -> normalized text


@dataclass
class SectionChange:
    section: str
    kind: str  # added | removed | modified
    before: str
    after: str
    unified: str


@dataclass
class Finding:
    section: str
    summary: str
    severity: str
    confidence: float
    affected_rules: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    effective_date: str | None = None


@dataclass
class Patch:
    source_id: str
    jurisdiction: str
    section: str
    rule_id: str
    action: str
    severity: str
    effective_date: str | None
    citation: str


@dataclass
class Alert:
    idempotency_key: str
    jurisdiction: str
    source_url: str
    severity: str
    confidence: float
    summary: str
    section: str
    patches: list[dict]
    detected_at: str

    def to_dict(self) -> dict:
        return asdict(self)
