"""Build a web page (one HTML file) from manual memory logs, to view in a browser.

Usage: python3 analysis/manual_page.py <manual-results dir> <out.html>

The directory holds one folder per run (run1/, run2/, ...), each with mem.csv
(the logger's output, one row a second, kB) and events.csv (lines
"time,<condition> <N> start|stop|end" from mark()).

The page has a tab per run (cost table and one chart per field) and an "All runs"
tab (mean and range of the cost across runs, and the runs lined up on their start
mark). For each run, before / running / after = median of the 60 s before its
start / stop / end mark, as in plot_manual.py. Charts show memory in use above
the start of the log, so for MemAvailable they plot the drop (up = more used).
"""

import csv
import json
import statistics
import sys
from pathlib import Path

FIELDS = [
    ("MemAvailable", "drop in MemAvailable: everything, including user memory; noisy"),
    ("SlabObjects", "kernel objects, from /proc/slabinfo"),
    ("SUnreclaim", "slab memory the kernel cannot drop under pressure"),
    ("KernelStack", "16 kB per process"),
    ("PageTables", "each process's memory maps"),
    ("Percpu", "per-CPU kernel data (network namespaces)"),
]
WINDOW = 60  # seconds before each mark that its median covers

# run.py's medians on Cortes (session 20261117-171752, N = 1000, kB per item), for comparison.
RUN_PY = {
    "P": {"SlabObjects": 22.0, "Percpu": 0.0, "MemAvailable": 125.3},
    "P+NS": {"SlabObjects": 206.1, "Percpu": 197.6, "MemAvailable": 501.5},
    "NS": {"SlabObjects": 228.6, "Percpu": 206.1, "MemAvailable": 425.6},
}

# A one-second rise in SlabObjects above this, with SUnreclaim and Percpu nearly flat,
# is reclaimable slab appearing at once: marked on the charts as a likely /proc read.
# (Making namespaces moves Percpu too, so it is not mistaken for one.)
JUMP_KB, FLAT_KB = 5000, 1000

src, out_file = Path(sys.argv[1]), sys.argv[2]
sign = {f: (-1 if f == "MemAvailable" else 1) for f, _ in FIELDS}


def load_run(folder):
    rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(open(folder / "mem.csv"))]
    t0 = rows[0]["time"]
    events = []
    for line in open(folder / "events.csv"):
        if line.strip():
            t, label = line.strip().split(",", 1)
            events.append({"t": int(t) - t0, "label": label})

    def median_before(field, t):
        values = [r[field] for r in rows if t - WINDOW <= r["time"] - t0 < t]
        return statistics.median(values) if values else None

    marks = {}
    for e in events:
        *name, what = e["label"].split()
        marks.setdefault(" ".join(name), {})[what] = e["t"]
    conditions = []
    for name, m in marks.items():
        if not {"start", "stop", "end"} <= m.keys():
            continue
        cond, n = name.rsplit(" ", 1)
        n = int(n)
        fields = []
        for field, _ in FIELDS:
            b, r, a = (median_before(field, m[k]) for k in ("start", "stop", "end"))
            fields.append({"field": field, "before": b, "running": r, "after": a,
                           "per": sign[field] * (r - b) / n, "left": sign[field] * (a - b),
                           "runpy": RUN_PY.get(cond, {}).get(field) if n == 1000 else None})
        conditions.append({"name": name, "n": n, "marks": m, "fields": fields})

    series = {}
    for field, _ in FIELDS:
        base = statistics.median(r[field] for r in rows if r["time"] - t0 < 30)
        series[field] = [[r["time"] - t0, round(sign[field] * (r[field] - base) / 1024, 3)] for r in rows]

    notes = []
    for prev, r in zip(rows, rows[1:]):
        rise = r["SlabObjects"] - prev["SlabObjects"]
        if (rise > JUMP_KB and abs(r["SUnreclaim"] - prev["SUnreclaim"]) < FLAT_KB
                and abs(r["Percpu"] - prev["Percpu"]) < FLAT_KB):
            notes.append({"field": "SlabObjects", "t": r["time"] - t0,
                          "label": f"+{rise / 1024:.1f} MB at once: /proc read?"})
    for c in conditions:
        # A /proc read in the first half of the running window puts most of its samples
        # after the jump, so it raises the SlabObjects median by about 10 kB per process.
        stop = c["marks"]["stop"]
        c["proc_read"] = [n["t"] - c["marks"]["start"] for n in notes if stop - WINDOW <= n["t"] < stop - WINDOW / 2]
    return {"series": series, "events": events, "conditions": conditions, "notes": notes,
            "rows": rows, "t0": t0}


runs = []
for folder in sorted((p for p in src.iterdir() if p.is_dir() and p.name.startswith("run")),
                     key=lambda p: int(p.name[3:]) if p.name[3:].isdigit() else 0):
    if (folder / "mem.csv").exists() and (folder / "events.csv").exists():
        run = load_run(folder)
        run.update(id=folder.name.replace("run", "run-"), name=folder.name.replace("run", "Run "),
                   file=f"{folder.name}/mem.csv", samples=len(run["rows"]))
        runs.append(run)

# All runs: per condition, the mean and range of the cost, and the runs lined up on
# their start mark (memory above each run's own "before" median, one point a second).
summary = []
names = list(dict.fromkeys(c["name"] for r in runs for c in r["conditions"]))  # order of first use
for name in names:
    per_run = [(r, c) for r in runs for c in r["conditions"] if c["name"] == name]
    fields = []
    for i, (field, _) in enumerate(FIELDS):
        pers = [c["fields"][i]["per"] for _, c in per_run]
        lefts = [c["fields"][i]["left"] for _, c in per_run]
        fields.append({"field": field, "mean": statistics.mean(pers), "min": min(pers), "max": max(pers),
                       "per_run": pers, "proc_read": [bool(c["proc_read"]) for _, c in per_run], "left": statistics.mean(lefts), "runpy": per_run[0][1]["fields"][i]["runpy"]})
    aligned = {}
    for field, _ in FIELDS:
        by_t = {}
        for r, c in per_run:
            b = next(f["before"] for f in c["fields"] if f["field"] == field)
            start = c["marks"]["start"]
            for row in r["rows"]:
                t = row["time"] - r["t0"] - start
                by_t.setdefault(t, []).append(sign[field] * (row[field] - b) / 1024)
        # Keep only seconds every run has, so the line never mixes run counts.
        aligned[field] = [[t, round(statistics.mean(v), 3), round(min(v), 3), round(max(v), 3)]
                          for t, v in sorted(by_t.items()) if len(v) == len(per_run)]
    stop = statistics.mean(c["marks"]["stop"] - c["marks"]["start"] for _, c in per_run)
    end = statistics.mean(c["marks"]["end"] - c["marks"]["start"] for _, c in per_run)
    summary.append({"name": name, "runs": [r["name"] for r, _ in per_run], "fields": fields,
                    "series": aligned, "events": [{"t": 0, "label": "start"}, {"t": round(stop), "label": "stop"},
                                                  {"t": round(end), "label": "end"}]})

for r in runs:
    del r["rows"], r["t0"]
data = {"fields": [{"name": f, "about": a} for f, a in FIELDS], "runs": runs, "summary": summary, "window": WINDOW}
template = (Path(__file__).parent / "manual_page.html").read_text()
Path(out_file).write_text(template.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
print("wrote", out_file, "with", len(runs), "runs")
