#!/usr/bin/env python3
"""A whole benchmark session: every condition x N, repeated, in a shuffled order.

Usage: sudo ./run_all.py [--dry-run] [--repeats K] [--n LIST] [--conditions LIST]
                         [--phase SECONDS] [--window SECONDS] [--seed S]

Do the Setup steps of the Measurement How-To first (build, quiet machine). Then
run this inside tmux, so a dropped SSH connection does not stop it. It:
  1. Records the machine with sysinfo.sh and measures 60 s of idle noise with
     noise_baseline.py.
  2. Runs run_cell.py for every condition x N, --repeats times each (default 5),
     in a shuffled order so slow drift on the machine does not line up with N.
  3. Retries each failed run once, at the end.
  4. Runs analyze.py, if it exists, to write report.txt.

Everything goes in results/session-<host>-<time>/ next to this script:
  manifest.json       settings, shuffle seed and the run order
  sysinfo.txt         output of sysinfo.sh
  noise-baseline.txt  output of noise_baseline.py
  runs.log            everything run_cell.py printed
  index.csv           one row per run: what it was, its folder, ok or failed
  <program>-<condition>-N<n>-r<k>/   one folder per run (see run_cell.py)

--dry-run prints the plan and how long it will take, without running anything.
Swap is never touched. Ctrl-C stops the session; finished runs are kept.
"""

import argparse
import csv
import json
import os
import random
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from run_cell import first_missing, give_back

SCRIPT_DIR = Path(__file__).resolve().parent
PROGRAM = SCRIPT_DIR / "small"
CONDITIONS = ["P", "P+NS", "NS"]
DEFAULT_N = [1, 10, 100, 1000]
NOISE_SECONDS = 60
RUN_OVERHEAD = 5  # seconds per run beyond its three phases; a rough guess, only for the time estimate
INDEX_COLUMNS = ["order", "condition", "n", "repeat", "attempt", "folder", "status", "exit_code",
                 "started", "seconds"]


def duration(seconds):
    """Format seconds as "1 h 05 min" or "12 min"."""
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def run_logged(cmd, log_path):
    """Run a command, appending everything it prints to a log. Return its exit status."""
    with open(log_path, "a") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for line in proc.stdout:
                log.write(line)
                log.flush()
        except KeyboardInterrupt:
            proc.wait()  # Ctrl-C reaches run_cell.py too; let it release everything first
            raise
        return proc.wait()


def main():
    ap = argparse.ArgumentParser(description="A whole benchmark session (see the Measurement How-To).")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without running anything")
    ap.add_argument("--repeats", type=int, default=5, help="runs of each condition x N (default 5)")
    ap.add_argument("--n", default=",".join(map(str, DEFAULT_N)), help="values of N (default 1,10,100,1000)")
    ap.add_argument("--conditions", default=",".join(CONDITIONS), help="conditions (default P,P+NS,NS)")
    ap.add_argument("--phase", type=float, default=30, help="seconds in each phase (default 30)")
    ap.add_argument("--window", type=float, default=10, help="seconds at the end of a phase to take the median over (default 10)")
    ap.add_argument("--seed", type=int, help="shuffle seed, to repeat a run order (default random)")
    args = ap.parse_args()

    ns = [int(x) for x in args.n.split(",")]
    conditions = args.conditions.split(",")
    if any(c not in CONDITIONS for c in conditions):
        ap.error(f"conditions must be from {','.join(CONDITIONS)}")
    if any(n < 1 for n in ns) or args.repeats < 1:
        ap.error("N and --repeats must be at least 1")

    seed = args.seed if args.seed is not None else random.randrange(2**32)
    plan = [(c, n, k) for c in conditions for n in ns for k in range(1, args.repeats + 1)]
    random.Random(seed).shuffle(plan)
    per_run = 3 * args.phase + RUN_OVERHEAD
    print(f"{len(plan)} runs ({len(conditions)} conditions x {len(ns)} values of N x {args.repeats} repeats), "
          f"seed {seed}")
    print(f"Estimated time: about {duration(NOISE_SECONDS + len(plan) * per_run)}")
    if args.dry_run:
        for i, (c, n, k) in enumerate(plan, 1):
            print(f"  {i:>3}  {c:<4}  N={n:<5}  repeat {k}")
        return

    if os.geteuid() != 0:
        sys.exit("run_all.py needs root: sudo ./run_all.py")
    for path, build in [(SCRIPT_DIR / "driver", "gcc -O2 -o driver driver.c"),
                        (PROGRAM, "gcc -O2 -static -o small small.c")]:
        if not os.access(path, os.X_OK):
            sys.exit(f"{path} not found; build it first: {build}")

    host = socket.gethostname()
    started_at = datetime.now()
    session = SCRIPT_DIR / "results" / f"session-{host}-{started_at.strftime('%Y%m%d-%H%M%S')}"
    created = first_missing(session) or session  # the folder to hand back to the sudo user at the end
    session.mkdir(parents=True)
    log = session / "runs.log"
    (session / "manifest.json").write_text(json.dumps({
        "host": host,
        "started": started_at.isoformat(timespec="seconds"),
        "program": PROGRAM.name,
        "conditions": conditions,
        "n": ns,
        "repeats": args.repeats,
        "phase_s": args.phase,
        "window_s": args.window,
        "seed": seed,
        "order": [{"condition": c, "n": n, "repeat": k} for c, n, k in plan],
    }, indent=2) + "\n")
    print(f"Session folder: {session}")

    interrupted = False
    try:
        print("Recording the machine (sysinfo.sh)", flush=True)
        with open(session / "sysinfo.txt", "w") as f:
            subprocess.run([str(SCRIPT_DIR / "sysinfo.sh")], stdout=f, stderr=subprocess.STDOUT)
        print(f"Measuring idle noise for {NOISE_SECONDS} s (noise_baseline.py)", flush=True)
        with open(session / "noise-baseline.txt", "w") as f:
            subprocess.run([sys.executable, str(SCRIPT_DIR / "noise_baseline.py"), str(NOISE_SECONDS)],
                           stdout=f, stderr=subprocess.STDOUT)

        with open(session / "index.csv", "w", newline="") as index_file:
            index = csv.writer(index_file)
            index.writerow(INDEX_COLUMNS)

            def do_run(order, condition, n, repeat, attempt):
                name = f"{PROGRAM.name}-{condition}-N{n}-r{repeat}" + ("-retry" if attempt > 1 else "")
                with open(log, "a") as f:
                    f.write(f"\n===== {order}: {name} =====\n")
                t = time.monotonic()
                started = datetime.now().isoformat(timespec="seconds")
                code = run_logged([sys.executable, str(SCRIPT_DIR / "run_cell.py"), condition, str(n),
                                   "--program", str(PROGRAM), "--out", str(session / name),
                                   "--phase", str(args.phase), "--window", str(args.window)], log)
                status = "ok" if code == 0 else "failed"
                index.writerow([order, condition, n, repeat, attempt, name, status, code, started,
                                round(time.monotonic() - t)])
                index_file.flush()
                return status

            failed = []
            for i, (c, n, k) in enumerate(plan, 1):
                status = do_run(i, c, n, k, 1)
                if status != "ok":
                    failed.append((i, c, n, k))
                left = (len(plan) - i + len(failed)) * per_run
                print(f"[{i:>3}/{len(plan)}] {c:<4} N={n:<5} repeat {k}  {status:<6}  "
                      f"about {duration(left)} left", flush=True)

            still_failed = 0
            for i, c, n, k in failed:
                status = do_run(i, c, n, k, 2)
                still_failed += status != "ok"
                print(f"[retry] {c:<4} N={n:<5} repeat {k}  {status}", flush=True)
            if still_failed:
                print(f"{still_failed} runs still failed after their retry; see index.csv and runs.log",
                      flush=True)
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted; finished runs are kept.", flush=True)
    finally:
        analyze = SCRIPT_DIR / "analyze.py"
        if analyze.exists():
            print("Writing report.txt (analyze.py)", flush=True)
            subprocess.run([sys.executable, str(analyze), str(session)])
        else:
            print("analyze.py not written yet, so no report.txt; see each run's summary.txt", flush=True)
        give_back(created)
        give_back(SCRIPT_DIR / "computer-state")  # sysinfo.sh and noise_baseline.py also save copies there

    print("interrupted" if interrupted else "done", session)
    sys.exit(1 if interrupted else 0)


if __name__ == "__main__":
    main()
