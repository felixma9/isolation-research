# /// script
# dependencies = ["plotext==5.3.2"]
# ///
"""Plot a manual memory log in the terminal, and print the cost per item.

Usage: uv run analysis/plot_manual.py <mem-*.csv> <events.csv>

mem-*.csv is the logger's output (one row a second, values in kB). events.csv has
lines "time,<condition> <N> start|stop|end" from mark(). For each condition:
  before  = median of the 60 s before "start"
  running = median of the 60 s before "stop"
  after   = median of the 60 s before "end"
"""

import csv
import statistics
import sys

import plotext as plt

FIELDS = ["MemAvailable", "SlabObjects", "SUnreclaim", "Percpu", "KernelStack", "PageTables"]
WINDOW = 60  # seconds

mem_file, events_file = sys.argv[1], sys.argv[2]
rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(open(mem_file))]
t0 = rows[0]["time"]
events = []  # (seconds since log start, "P 1000 start")
for line in open(events_file):
    t, label = line.strip().split(",", 1)
    events.append((int(t) - t0, label))


def median_before(field, t):
    """Median of `field` over the WINDOW seconds before time t."""
    values = [r[field] for r in rows if t - WINDOW <= r["time"] - t0 < t]
    return statistics.median(values) if values else None


# One small plot per field: change from the first row, in MB, with the events as lines.
times = [r["time"] - t0 for r in rows]
plt.limitsize(False, False)  # draw full size even when the terminal is smaller
plt.subplots(len(FIELDS), 1)
plt.plotsize(100, 14 * len(FIELDS))
for i, field in enumerate(FIELDS, 1):
    plt.subplot(i, 1)
    plt.plot(times, [(r[field] - rows[0][field]) / 1024 for r in rows], marker="braille")
    for t, _ in events:
        plt.vline(t, "red")
    plt.title(f"{field}: change since log start (MB); red = start/stop/end")
plt.subplot(len(FIELDS), 1)
plt.xlabel("seconds since log start")
plt.show()

# Cost table, one block per condition that has start, stop and end.
marks = {}
for t, label in events:
    *name, what = label.split()
    marks.setdefault(" ".join(name), {})[what] = t
print()
for name, m in marks.items():
    if not {"start", "stop", "end"} <= m.keys():
        print(f"{name}: missing a mark (have {sorted(m)}), skipped")
        continue
    n = int(name.split()[-1])
    print(f"{name}   (medians of the {WINDOW} s before each mark; kB)")
    print(f"  {'':12} {'before':>12} {'running':>12} {'after':>12} {'cost/item':>10} {'left behind':>12}")
    for field in FIELDS:
        b, r, a = (median_before(field, m[k]) for k in ("start", "stop", "end"))
        cost = (b - r) if field == "MemAvailable" else (r - b)  # MemAvailable falls as memory is used
        left = (b - a) if field == "MemAvailable" else (a - b)
        print(f"  {field:12} {b:12,.0f} {r:12,.0f} {a:12,.0f} {cost / n:+10.1f} {left:+12,.0f}")
    print()
