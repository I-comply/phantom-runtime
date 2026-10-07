"""
Edge-computed telemetry anomaly detection filter.

Rolling-window statistics (mean/stddev z-score and median-ratio spike test) run
in local memory over log-stream samples. Anomalies are isolated and tagged
before metrics are batched to a centralized telemetry sink. Stdlib only.
"""

import json
import math
import re
import statistics
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Callable, Deque, Dict, Iterable, List, Optional

_KV = re.compile(r'([A-Za-z_][\w.]*)=(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)')


@dataclass
class Sample:
    metric: str
    value: float
    ts: float = field(default_factory=time.time)


@dataclass
class Anomaly:
    metric: str
    value: float
    ts: float
    kind: str  # "deviation" | "spike"
    zscore: float
    baseline_mean: float
    baseline_median: float


def parse_log_line(line: str, ts: Optional[float] = None) -> List[Sample]:
    """Extract numeric fields from a JSON or key=value log line."""
    ts = time.time() if ts is None else ts
    line = line.strip()
    if not line:
        return []
    if line.startswith("{"):
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            return [
                Sample(k, float(v), ts)
                for k, v in obj.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            ]
    return [Sample(k, float(v), ts) for k, v in _KV.findall(line)]


class RollingWindow:
    """Fixed-size window with O(1) mean/variance via running sums."""

    def __init__(self, size: int):
        self.size = size
        self._buf: Deque[float] = deque()
        self._sum = 0.0
        self._sumsq = 0.0

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, x: float) -> None:
        self._buf.append(x)
        self._sum += x
        self._sumsq += x * x
        if len(self._buf) > self.size:
            old = self._buf.popleft()
            self._sum -= old
            self._sumsq -= old * old

    @property
    def mean(self) -> float:
        return self._sum / len(self._buf)

    @property
    def std(self) -> float:
        n = len(self._buf)
        var = (self._sumsq - self._sum * self._sum / n) / n
        return math.sqrt(var) if var > 0 else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self._buf)


class AnomalyFilter:
    """
    Per-metric rolling-window detector.

    - deviation: |z| >= z_threshold (std floored at min_std_frac * |mean|)
    - spike: value >= spike_ratio * median (resource surge, positive only)

    Anomalous samples are withheld from the baseline so spikes don't mask
    themselves; after `level_shift_after` consecutive anomalies the window is
    rebased onto the new level.
    """

    def __init__(
        self,
        window: int = 120,
        min_samples: int = 20,
        z_threshold: float = 4.0,
        spike_ratio: float = 3.0,
        min_std_frac: float = 0.01,
        level_shift_after: int = 10,
    ):
        self.window = window
        self.min_samples = min_samples
        self.z_threshold = z_threshold
        self.spike_ratio = spike_ratio
        self.min_std_frac = min_std_frac
        self.level_shift_after = level_shift_after
        self._windows: Dict[str, RollingWindow] = {}
        self._streak: Dict[str, int] = {}

    def observe(self, s: Sample) -> Optional[Anomaly]:
        if not math.isfinite(s.value):
            return None
        w = self._windows.setdefault(s.metric, RollingWindow(self.window))
        if len(w) < self.min_samples:
            w.push(s.value)
            return None

        mean, med = w.mean, w.median
        std = max(w.std, self.min_std_frac * abs(mean), 1e-9)
        z = (s.value - mean) / std
        kind = None
        if abs(z) >= self.z_threshold:
            kind = "deviation"
        if med > 0 and s.value >= self.spike_ratio * med:
            kind = "spike"

        if kind is None:
            self._streak[s.metric] = 0
            w.push(s.value)
            return None

        streak = self._streak.get(s.metric, 0) + 1
        self._streak[s.metric] = streak
        if streak >= self.level_shift_after:
            self._windows[s.metric] = RollingWindow(self.window)
            self._windows[s.metric].push(s.value)
            self._streak[s.metric] = 0
        return Anomaly(s.metric, s.value, s.ts, kind, z, mean, med)


class TelemetryBatcher:
    """
    Filters a sample stream and flushes batches to a sink callable.
    Each batch: {"metrics": {name: {count,sum,min,max}}, "anomalies": [...]}.
    Anomalies are forwarded in full; normal samples are aggregated.
    """

    def __init__(
        self,
        sink: Callable[[dict], None],
        detector: Optional[AnomalyFilter] = None,
        batch_size: int = 500,
        flush_interval: float = 10.0,
    ):
        self.sink = sink
        self.detector = detector or AnomalyFilter()
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._reset(time.monotonic())

    def _reset(self, now: float) -> None:
        self._agg: Dict[str, dict] = {}
        self._anomalies: List[Anomaly] = []
        self._n = 0
        self._started = now

    def add(self, s: Sample) -> Optional[Anomaly]:
        a = self.detector.observe(s)
        m = self._agg.get(s.metric)
        if m is None:
            m = self._agg[s.metric] = {"count": 0, "sum": 0.0, "min": s.value, "max": s.value}
        m["count"] += 1
        m["sum"] += s.value
        m["min"] = min(m["min"], s.value)
        m["max"] = max(m["max"], s.value)
        if a:
            self._anomalies.append(a)
        self._n += 1
        if self._n >= self.batch_size or time.monotonic() - self._started >= self.flush_interval:
            self.flush()
        return a

    def add_lines(self, lines: Iterable[str]) -> List[Anomaly]:
        out = []
        for line in lines:
            for s in parse_log_line(line):
                a = self.add(s)
                if a:
                    out.append(a)
        return out

    def flush(self) -> None:
        if self._n:
            batch = {"metrics": self._agg, "anomalies": [asdict(a) for a in self._anomalies]}
            self._reset(time.monotonic())
            self.sink(batch)
