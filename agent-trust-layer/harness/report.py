"""Render graphs from reports/results_*.json -> reports/*.png"""
import json, statistics, sys
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = Path(sys.argv[1] if len(sys.argv) > 1 else "reports")
load = lambda n: json.load(open(R / n))
runs = {"subprocess (before fix)": load("results_subprocess_before_fix.json"),
        "subprocess (after fix)": load("results_subprocess.json"), "docker (after fix)": load("results_docker.json")}
C = {"subprocess (before fix)": "#c0392b", "subprocess (after fix)": "#2e86c1", "docker (after fix)": "#27ae60"}

fig, ax = plt.subplots(figsize=(7, 4))
for i, (k, v) in enumerate(runs.items()):
    s = v["summary"]
    ax.bar(i, s["pass"], color=C[k]); ax.bar(i, s["fail"], bottom=s["pass"], color="#7f8c8d")
    ax.text(i, s["requests"] + 10, f'{s["pass"]}/{s["requests"]}', ha="center")
ax.set_ylim(0, 860); ax.set_xticks(range(3)); ax.set_xticklabels([k.replace(" (", "\n(") for k in runs]); ax.set_ylabel("requests")
ax.set_title("Scenario outcomes matching expectation (grey = unexpected)"); fig.tight_layout(); fig.savefig(R / "outcomes.png", dpi=120)

fig, ax = plt.subplots(figsize=(7, 4))
for k, v in list(runs.items())[1:]:
    ms = sorted(r["ms"] for r in v["records"])
    ax.plot(ms, [(i + 1) / len(ms) for i in range(len(ms))], label=k, color=C[k])
ax.set_xscale("log"); ax.set_xlabel("latency ms (log)"); ax.set_ylabel("CDF"); ax.legend(); ax.grid(alpha=.3)
ax.set_title("Latency CDF"); fig.tight_layout(); fig.savefig(R / "latency_cdf.png", dpi=120)

fig, ax = plt.subplots(figsize=(8, 7))
by = defaultdict(lambda: defaultdict(list))
for k in ("subprocess (after fix)", "docker (after fix)"):
    for r in runs[k]["records"]:
        by[r["scenario"]][k].append(r["ms"])
names = sorted(by, key=lambda n: statistics.median(by[n]["docker (after fix)"]))
for j, k in enumerate(("subprocess (after fix)", "docker (after fix)")):
    ax.barh([i + j * .4 for i in range(len(names))], [statistics.median(by[n][k]) for n in names], .4, label=k, color=C[k])
ax.set_yticks([i + .2 for i in range(len(names))]); ax.set_yticklabels(names, fontsize=7); ax.set_xscale("log")
ax.set_xlabel("median latency ms (log)"); ax.legend(); ax.set_title("Median latency by scenario"); fig.tight_layout(); fig.savefig(R / "latency_by_scenario.png", dpi=120)

fig, ax = plt.subplots(figsize=(6, 3.5))
ks = list(runs); v = [runs[k]["summary"]["throughput_rps"] for k in ks]
ax.bar(range(3), v, color=[C[k] for k in ks]); ax.set_xticks(range(3)); ax.set_xticklabels([k.replace(" (", "\n(") for k in ks])
for i, x in enumerate(v):
    ax.text(i, x + 2, str(x), ha="center")
ax.set_ylabel("requests/s"); ax.set_title("Throughput (24 / 24 / 6 agent processes)"); fig.tight_layout(); fig.savefig(R / "throughput.png", dpi=120)
print("ok")
