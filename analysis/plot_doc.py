# /// script
# dependencies = ["matplotlib==3.9.2"]
# ///
"""Plot one field over the whole manual run, as a PNG for the team doc.

Usage: uv run analysis/plot_doc.py <manual-results dir> <field> <out.png>

Draws every runN/ folder's mem.csv as one line, lined up on its first "start"
mark, as change in MB from the median of the 60 s before that mark. Each
condition's running time (start to stop) is shaded and labelled; solid lines
are start marks, dashed lines stop marks (mean time across runs).
"""

import csv
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

src, field, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e6e5e0"

runs = sorted((p for p in src.iterdir() if p.is_dir() and p.name[3:].isdigit()), key=lambda p: int(p.name[3:]))
marks = {}  # (condition, start|stop|end) -> [seconds after first start, per run]
fig, ax = plt.subplots(figsize=(10, 4), dpi=160)
for i, run in enumerate(runs):
    rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(open(run / "mem.csv"))]
    events = [(int(t), label.split()) for t, label in
              (line.strip().split(",", 1) for line in open(run / "events.csv") if line.strip())]
    t0 = events[0][0]
    for t, (*name, what) in events:
        marks.setdefault((name[0], what), []).append(t - t0)
    base = statistics.median(r[field] for r in rows if -60 <= r["time"] - t0 < 0)
    xs = [(r["time"] - t0) / 60 for r in rows]
    ys = [(r[field] - base) / 1024 for r in rows]
    ax.plot(xs, ys, color=COLORS[i], linewidth=1.6, label=run.name.replace("run", "Run "))

top = ax.get_ylim()[1]
for cond in dict.fromkeys(c for c, _ in marks):
    start = statistics.mean(marks[(cond, "start")]) / 60
    stop = statistics.mean(marks[(cond, "stop")]) / 60
    ax.axvspan(start, stop, color="#f1f0ec", zorder=0)
    ax.axvline(start, color=MUTED, linewidth=1, zorder=1)
    ax.axvline(stop, color=MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    ax.text((start + stop) / 2, top, f"{cond} running", ha="center", va="bottom", fontsize=9, color=INK)
    ax.text(start, ax.get_ylim()[0], " start", ha="left", va="bottom", fontsize=8, color=MUTED)
    ax.text(stop, ax.get_ylim()[0], " stop", ha="left", va="bottom", fontsize=8, color=MUTED)

ax.set_title(f"{field} during the manual runs (1000 items per condition, Cortes, Nov 23)",
             fontsize=11, color=INK, loc="left", pad=18)
ax.set_xlabel("minutes since the first start mark", fontsize=9, color=MUTED)
ax.set_ylabel(f"{field}: change from before (MB)", fontsize=9, color=MUTED)
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(GRID)
ax.tick_params(colors=MUTED, labelsize=8)
ax.legend(frameon=False, fontsize=8, loc="upper right", bbox_to_anchor=(1, 1.12), ncol=len(runs))
fig.tight_layout()
fig.savefig(out)
print("wrote", out)
