#!/usr/bin/env python3
# /// script
# dependencies = ["plotly"]
# ///
"""Graph one session: kernel memory cost per item against N, one line per condition.

Usage:
  uv run analyze.py results/benchmark1/session-<host>-<time>
  (or: python3 analyze.py ..., if plotly is installed)

For every run that passed (the retry, where a run failed first):
  kernel total = SlabObjects + Percpu + VmallocUsed + KernelStack + PageTables
  cost         = median of the last `window` s of running - same for before
  cost per item = cost / N
(summary.txt takes the median of each counter separately; summing those gives
the same answer at large N, and slightly different numbers at N = 1 or 10.)

Prints a table of the median per condition and N, and saves an interactive graph
as cost-per-item.html in the session folder (open it in a browser; it loads the
Plotly library from the web, which keeps the file small). Dots are single runs;
lines join the medians of the repeats. Hover for
values; drag to zoom; double-click to show everything.
"""

import csv
import json
import math
import statistics
import sys
from pathlib import Path

import plotly.graph_objects as go

KERNEL = ["SlabObjects", "Percpu", "VmallocUsed", "KernelStack", "PageTables"]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SYMBOLS = ["circle", "square", "triangle-up", "diamond", "triangle-down", "cross", "x", "star"]
INK, MUTED, RULE = "#1f1f1d", "#5c5c58", "#e6e6e3"


def phase_value(rows, phase, window):
    """Median kernel total over the last `window` seconds of a phase."""
    rows = [r for r in rows if r["phase"] == phase]
    end = float(rows[-1]["t"])
    return statistics.median(sum(float(r[k]) for k in KERNEL)
                             for r in rows if float(r["t"]) > end - window)


def load(session):
    """Return {(condition, n): [(cost per item, folder) of each passing run]}, and the manifest."""
    manifest = json.loads((session / "manifest.json").read_text())
    window = manifest["window_s"]
    passed = {}  # (condition, n, repeat) -> folder; a later attempt replaces an earlier one
    with open(session / "index.csv") as f:
        for r in csv.DictReader(f):
            if r["status"] == "ok":
                passed[(r["condition"], int(r["n"]), int(r["repeat"]))] = r["folder"]
    costs = {}
    for (condition, n, _), folder in sorted(passed.items()):
        with open(session / folder / "trace.csv") as f:
            rows = list(csv.DictReader(f))
        cost = phase_value(rows, "running", window) - phase_value(rows, "before", window)
        costs.setdefault((condition, n), []).append((cost / n, folder))
    return costs, manifest


def median(runs):
    return statistics.median(cost for cost, _ in runs)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    session = Path(sys.argv[1])
    costs, manifest = load(session)
    conditions = [c for c in manifest["conditions"] if any(k[0] == c for k in costs)]
    ns = sorted({n for _, n in costs})

    # Table: median (and number of runs) per condition and N.
    print(f"Kernel memory cost per item, kB (median of passing runs) - {session.name}")
    print(f"{'N':>6}" + "".join(f"{c:>14}" for c in conditions))
    for n in ns:
        cells = [f"{median(costs[c, n]):.0f} (n={len(costs[c, n])})" if (c, n) in costs else "-"
                 for c in conditions]
        print(f"{n:>6}" + "".join(f"{x:>14}" for x in cells))

    # Graph: dots for single runs, a line through the medians, the name at the line's end.
    fig = go.Figure()
    for i, c in enumerate(conditions):
        color, symbol = COLORS[i % len(COLORS)], SYMBOLS[i % len(SYMBOLS)]
        xs = [n for n in ns if (c, n) in costs]
        runs = [(n, cost, folder) for n in xs for cost, folder in costs[c, n]]
        fig.add_trace(go.Scatter(  # single runs: faint, hover shows which run
            x=[r[0] for r in runs], y=[r[1] for r in runs], mode="markers", legendgroup=c,
            showlegend=False, name=c, customdata=[r[2] for r in runs],
            marker=dict(color=color, symbol=symbol, size=8, opacity=0.35),
            hovertemplate="%{customdata}<br>%{y:.0f} kB per item<extra></extra>"))
        medians = [median(costs[c, n]) for n in xs]
        fig.add_trace(go.Scatter(  # medians: the line
            x=xs, y=medians, mode="lines+markers", legendgroup=c, name=c,
            customdata=[len(costs[c, n]) for n in xs],
            line=dict(color=color, width=2),
            marker=dict(color=color, symbol=symbol, size=10, line=dict(color="white", width=2)),
            hovertemplate=f"{c}, N = %{{x}}<br>median %{{y:.0f}} kB per item (%{{customdata}} runs)<extra></extra>"))
        # On a log axis, Plotly places annotations by log10 of the value.
        fig.add_annotation(x=math.log10(xs[-1]), y=medians[-1], text=c, showarrow=False, xanchor="left",
                           xshift=10, font=dict(color=INK, size=12))

    # Start the view fitted to the medians, so one wild run at small N does not squash the rest.
    all_medians = [median(v) for v in costs.values()]
    lo, hi = min(0, *all_medians), max(0, *all_medians)
    lo, hi = lo - 0.15 * (hi - lo), hi + 0.15 * (hi - lo)
    outside = sum(not lo <= cost <= hi for v in costs.values() for cost, _ in v)
    if outside:
        fig.add_annotation(xref="paper", yref="paper", x=0, y=-0.2, xanchor="left", showarrow=False,
                           text=f"{outside} single runs are outside this view; double-click the graph to show all",
                           font=dict(color=MUTED, size=11))

    fig.update_layout(
        title=dict(text=f"{manifest['benchmark']} on {manifest['host']}, {manifest['started'][:10]}",
                   x=0, xanchor="left", font=dict(color=INK, size=16)),
        template="plotly_white", width=900, height=550, hovermode="closest",
        legend=dict(x=1.02, y=1, xanchor="left"),
        margin=dict(r=140, b=110),
        font=dict(color=MUTED),
    )
    fig.update_xaxes(type="log", tickvals=ns, ticktext=[str(n) for n in ns], showgrid=False,
                     title="N (number of items held at once)", linecolor="#9a9a96")
    fig.update_yaxes(range=[lo, hi], gridcolor=RULE, zeroline=True, zerolinecolor="#9a9a96",
                     title="Kernel memory cost per item (kB)", linecolor="#9a9a96")
    out = session / "cost-per-item.html"
    fig.write_html(out, include_plotlyjs="cdn")  # loads Plotly from the web: small file, needs internet
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
