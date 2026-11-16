#!/usr/bin/env python3
"""Run a benchmark: a whole session, or a single run.

Usage:
  ./run.py <benchmark> --dry-run              print the run order and how long it will take
  sudo ./run.py <benchmark>                   a whole session (run it inside tmux)
  sudo ./run.py <benchmark> --cell P+NS 10    one run of one condition and N

<benchmark> is a folder such as benchmark1, holding main.c and config.py.
Build first with `make`. Results go in results/<benchmark>/.
See lib/session.py and lib/cell.py for what a session and a run do.
"""

import argparse
import importlib
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

from lib.cell import BUILD, ROOT, run_cell
from lib.session import run_session


def main():
    ap = argparse.ArgumentParser(description="Run a benchmark (see the Measurement How-To).")
    ap.add_argument("benchmark", help="benchmark folder, such as benchmark1")
    ap.add_argument("--cell", nargs=2, metavar=("CONDITION", "N"), help="do one run instead of a session")
    ap.add_argument("--out", type=Path, help="with --cell: folder for the run's files")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without running anything")
    ap.add_argument("--repeats", type=int, help="runs of each condition x N (default from config.py)")
    ap.add_argument("--n", help="comma-separated values of N (default from config.py)")
    ap.add_argument("--conditions", help="comma-separated conditions (default: all in config.py)")
    ap.add_argument("--seed", type=int, help="shuffle seed, to repeat a run order (default random)")
    ap.add_argument("--phase", type=float, default=30, help="seconds in each phase (default 30)")
    ap.add_argument("--window", type=float, default=10,
                    help="seconds at the end of a phase to take the median over (default 10)")
    ap.add_argument("--interval", type=float, default=1, help="seconds between samples (default 1)")
    args = ap.parse_args()

    name = args.benchmark.strip("/")
    if not (ROOT / name / "config.py").exists():
        ap.error(f"no {name}/config.py")
    bench = importlib.import_module(f"{name}.config")

    if args.cell:
        condition, n = args.cell[0], int(args.cell[1])
        conditions, ns = [condition], [n]
    else:
        conditions = args.conditions.split(",") if args.conditions else list(bench.CONDITIONS)
        ns = [int(x) for x in args.n.split(",")] if args.n else bench.N
    repeats = args.repeats or bench.REPEATS
    if any(c not in bench.CONDITIONS for c in conditions):
        ap.error(f"conditions must be from {','.join(bench.CONDITIONS)}")
    if any(n < 1 for n in ns) or repeats < 1:
        ap.error("N and --repeats must be at least 1")

    if not args.dry_run:
        if os.geteuid() != 0:
            sys.exit("needs root (to create namespaces and read /proc/slabinfo): sudo ./run.py ...")
        for program in (name, bench.WORKLOAD):
            if not os.access(BUILD / program, os.X_OK):
                sys.exit(f"build/{program} not found; build first with `make`")

    if args.cell:
        out = args.out or ROOT / "results" / name / (
            f"{condition}-N{n}-{socket.gethostname()}-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        ok = run_cell(name, bench, condition, n, out, args.phase, args.window, args.interval)
        sys.exit(0 if ok else 1)
    sys.exit(run_session(name, bench, conditions, ns, repeats, args.phase, args.window,
                         args.seed, args.dry_run))


if __name__ == "__main__":
    main()
