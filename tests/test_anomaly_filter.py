import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "observability"))

from anomaly_filter import AnomalyFilter, Sample, TelemetryBatcher, parse_log_line


def _warm(f, n=50, base=100.0, seed=1):
    r = random.Random(seed)
    for i in range(n):
        assert f.observe(Sample("cpu", base + r.uniform(-2, 2), i)) is None


def test_spike_detected():
    f = AnomalyFilter()
    _warm(f)
    a = f.observe(Sample("cpu", 400.0))
    assert a and a.kind == "spike"


def test_drop_deviation_detected():
    f = AnomalyFilter()
    _warm(f)
    a = f.observe(Sample("cpu", 10.0))
    assert a and a.kind == "deviation" and a.zscore < 0


def test_no_false_positive_on_noise():
    f = AnomalyFilter()
    r = random.Random(2)
    assert all(f.observe(Sample("m", 50 + r.gauss(0, 1))) is None for _ in range(500))


def test_level_shift_rebases():
    f = AnomalyFilter(level_shift_after=5)
    _warm(f)
    hits = [f.observe(Sample("cpu", 500.0)) for _ in range(12)]
    assert hits[0] is not None and hits[-1] is None


def test_parse_lines():
    assert {s.metric: s.value for s in parse_log_line("a=1 b=2.5 msg=x")} == {"a": 1.0, "b": 2.5}
    assert {s.metric for s in parse_log_line('{"cpu": 3, "ok": true, "n": "x"}')} == {"cpu"}


def test_batcher_flushes_anomalies():
    out = []
    b = TelemetryBatcher(out.append, batch_size=1000)
    r = random.Random(3)
    b.add_lines(f"cpu={100 + r.uniform(-2, 2)}" for _ in range(50))
    b.add_lines(["cpu=900"])
    b.flush()
    assert len(out) == 1
    assert out[0]["metrics"]["cpu"]["count"] == 51
    assert len(out[0]["anomalies"]) == 1
