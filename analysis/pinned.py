"""Cost per item from the pinned N-scaling runs (one mem.csv, events-runN.csv).

Usage: python3 analysis/pinned.py <dir> [out.json]

before  = median of the 60 s before the start mark
running = median of 30-60 s after the start command returned (stop - 90 .. stop - 60),
          so the once-a-minute /proc read (processes > 60 s old) stays out
after   = median of the 60 s before the end mark
"""
import csv, json, statistics, sys
from pathlib import Path

src = Path(sys.argv[1])
rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(open(src / "mem.csv"))]
times = [r["time"] for r in rows]

def med(field, a, b):
    v = [r[field] for r in rows if a <= r["time"] < b]
    return statistics.median(v)

def derived(f, a, b):
    if f == "KS+PT": return med("KernelStack", a, b) + med("PageTables", a, b)
    if f == "Unreclaimable": return med("SUnreclaim", a, b) + med("Percpu", a, b) + derived("KS+PT", a, b)
    if f == "Kernel": return med("SlabObjects", a, b) + med("Percpu", a, b) + derived("KS+PT", a, b)
    if f == "MemAvailable drop": return -med("MemAvailable", a, b)
    return med(f, a, b)

FIELDS = ["SUnreclaim", "Percpu", "KS+PT", "Unreclaimable", "SlabObjects", "Kernel", "MemAvailable drop"]
out = []
for ev in sorted(src.glob("events-run*.csv")):
    run = int(ev.stem.split("run")[1])
    marks = {}
    for line in open(ev):
        t, label = line.strip().split(",", 1)
        cond, n, what = label.split()
        marks.setdefault((cond, int(n)), {})[what] = int(t)
    for (cond, n), m in marks.items():
        rec = {"run": run, "cond": cond, "n": n}
        for f in FIELDS:
            b = derived(f, m["start"] - 60, m["start"])
            r = derived(f, m["stop"] - 90, m["stop"] - 60)
            r_late = derived(f, m["stop"] - 60, m["stop"])
            a = derived(f, m["end"] - 60, m["end"])
            rec[f] = {"per": (r - b) / n, "per_late": (r_late - b) / n, "left": a - b}
        out.append(rec)
json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else "/dev/stdout", "w"), indent=1)
