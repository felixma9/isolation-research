#!/usr/bin/env python3
# /// script
# dependencies = ["plotly", "matplotlib"]
# ///
"""Graph one session: kernel memory cost per item against N, one line per condition.

Usage:
  uv run analyze.py results/benchmark1/session-<host>-<time>            interactive (Plotly)
  uv run analyze.py results/benchmark1/session-<host>-<time> --static   static (matplotlib)
  (or python3 instead of uv run, if plotly / matplotlib is installed)

For every run that passed (the retry, where a run failed first):
  kernel total = SlabObjects + Percpu + VmallocUsed + KernelStack + PageTables
  cost         = median of the last `window` s of running - same for before
  cost per item = cost / N
(summary.txt takes the median of each counter separately; summing those gives
the same answer at large N, and slightly different numbers at N = 1 or 10.)

Prints a table of the median per condition and N, and saves the graph in the
session folder:
  interactive  cost-per-item.html: open in a browser (it loads the Plotly library
               from the web). Hover for values, drag to zoom, double-click to show all.
  --static     cost-per-item.pdf (vector, for papers) and cost-per-item.png.
Dots are single runs; lines join the medians of the repeats.
"""

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

KERNEL = ["SlabObjects", "Percpu", "VmallocUsed", "KernelStack", "PageTables"]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
PLOTLY_SYMBOLS = ["circle", "square", "triangle-up", "diamond", "triangle-down", "cross", "x", "star"]
MPL_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
INK, MUTED, RULE, AXIS = "#1f1f1d", "#5c5c58", "#e6e6e3", "#9a9a96"
X_TITLE = "N (number of items held at once)"
Y_TITLE = "Kernel memory cost per item (kB)"


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


def prepare(costs, conditions, ns):
    """What both graphs draw: one series per condition, and a view fitted to the medians
    (so one wild run at small N does not squash the rest)."""
    series = []
    for i, c in enumerate(conditions):
        xs = [n for n in ns if (c, n) in costs]
        series.append(dict(
            name=c, i=i % len(COLORS), color=COLORS[i % len(COLORS)], xs=xs,
            runs=[(n, cost, folder) for n in xs for cost, folder in costs[c, n]],
            medians=[median(costs[c, n]) for n in xs],
            counts=[len(costs[c, n]) for n in xs]))
    all_medians = [m for s in series for m in s["medians"]]
    lo, hi = min(0, *all_medians), max(0, *all_medians)
    lo, hi = lo - 0.15 * (hi - lo), hi + 0.15 * (hi - lo)
    outside = sum(not lo <= cost <= hi for s in series for _, cost, _ in s["runs"])
    return series, lo, hi, outside


def interactive(series, ns, lo, hi, outside, title, out):
    """Plotly graph as a small HTML file."""
    import plotly.graph_objects as go

    fig = go.Figure()
    for s in series:
        c, color, symbol = s["name"], s["color"], PLOTLY_SYMBOLS[s["i"]]
        fig.add_trace(go.Scatter(  # single runs: faint, hover shows which run
            x=[r[0] for r in s["runs"]], y=[r[1] for r in s["runs"]], mode="markers",
            legendgroup=c, showlegend=False, name=c, customdata=[r[2] for r in s["runs"]],
            marker=dict(color=color, symbol=symbol, size=8, opacity=0.35),
            hovertemplate="%{customdata}<br>%{y:.0f} kB per item<extra></extra>"))
        fig.add_trace(go.Scatter(  # medians: the line
            x=s["xs"], y=s["medians"], mode="lines+markers", legendgroup=c, name=c,
            customdata=s["counts"], line=dict(color=color, width=2),
            marker=dict(color=color, symbol=symbol, size=10, line=dict(color="white", width=2)),
            hovertemplate=f"{c}, N = %{{x}}<br>median %{{y:.0f}} kB per item (%{{customdata}} runs)<extra></extra>"))
        # On a log axis, Plotly places annotations by log10 of the value.
        fig.add_annotation(x=math.log10(s["xs"][-1]), y=s["medians"][-1], text=c, showarrow=False,
                           xanchor="left", xshift=10, font=dict(color=INK, size=12))
    if outside:
        fig.add_annotation(xref="paper", yref="paper", x=0, y=-0.2, xanchor="left", showarrow=False,
                           text=f"{outside} single runs are outside this view; double-click the graph to show all",
                           font=dict(color=MUTED, size=11))
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(color=INK, size=16)),
        template="plotly_white", width=900, height=550, hovermode="closest",
        legend=dict(x=1.02, y=1, xanchor="left"), margin=dict(r=140, b=110), font=dict(color=MUTED))
    fig.update_xaxes(type="log", tickvals=ns, ticktext=[str(n) for n in ns], showgrid=False,
                     title=X_TITLE, linecolor=AXIS)
    fig.update_yaxes(range=[lo, hi], gridcolor=RULE, zeroline=True, zerolinecolor=AXIS,
                     title=Y_TITLE, linecolor=AXIS)
    fig.write_html(out / "cost-per-item.html", include_plotlyjs="cdn")  # small file, needs internet
    return [out / "cost-per-item.html"]


def static(series, ns, lo, hi, outside, title, out):
    """matplotlib graph as PDF (vector) and PNG."""
    import matplotlib

    matplotlib.use("Agg")  # write files; no screen needed
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullLocator

    fig, ax = plt.subplots(figsize=(8, 5))
    for s in series:
        color, marker = s["color"], MPL_MARKERS[s["i"]]
        ax.scatter([r[0] for r in s["runs"]], [r[1] for r in s["runs"]], s=18, color=color,
                   alpha=0.35, marker=marker, linewidths=0)
        ax.plot(s["xs"], s["medians"], color=color, linewidth=2, marker=marker, markersize=7,
                label=s["name"], markeredgecolor="white", markeredgewidth=1.5)
        ax.annotate(s["name"], (s["xs"][-1], s["medians"][-1]), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
    if outside:
        ax.text(0, -0.15, f"{outside} single runs fall outside the view and are not drawn "
                "(the medians include them)", transform=ax.transAxes, fontsize=8, color=MUTED)
    ax.set_xscale("log")
    ax.set_xticks(ns, [str(n) for n in ns])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_ylim(lo, hi)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.set_xlabel(X_TITLE, color=INK)
    ax.set_ylabel(Y_TITLE, color=INK)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", color=RULE, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.08, 1))
    ax.margins(x=0.08)
    fig.tight_layout()
    paths = [out / "cost-per-item.pdf", out / "cost-per-item.png"]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=200)
    return paths


def main():
    ap = argparse.ArgumentParser(description="Graph one session: cost per item against N.")
    ap.add_argument("session", type=Path, help="a session folder, such as results/benchmark1/session-...")
    ap.add_argument("--static", action="store_true",
                    help="matplotlib PDF and PNG instead of the interactive Plotly HTML")
    args = ap.parse_args()
    session = args.session
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

    series, lo, hi, outside = prepare(costs, conditions, ns)
    title = f"{manifest['benchmark']} on {manifest['host']}, {manifest['started'][:10]}"
    draw = static if args.static else interactive
    for path in draw(series, ns, lo, hi, outside, title, session):
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
