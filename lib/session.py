"""A whole benchmark session: every condition x N, repeated, in a shuffled order.
Started by run.py; works the same for every benchmark. It:
  1. Records the machine with machine/sysinfo.sh and measures 60 s of idle noise
     with machine/noise_baseline.py.
  2. Does one run (see cell.py) for every condition x N, `repeats` times each,
     in a shuffled order so slow drift on the machine does not line up with N.
     Each run is its own `run.py --cell` process.
  3. Retries each failed run once, at the end.

Everything goes in results/<benchmark>/session-<host>-<time>/:
  manifest.json       settings, shuffle seed and the run order
  sysinfo.txt         output of sysinfo.sh
  noise-baseline.txt  output of noise_baseline.py
  runs.log            everything the runs printed
  index.csv           one row per run: what it was, its folder, ok or failed
  <condition>-N<n>-r<k>/   one folder per run (see cell.py)

Swap is never touched. Ctrl-C stops the session; finished runs are kept.
"""

import csv
import json
import random
import socket
import subprocess
import sys
import time
from datetime import datetime

from lib.cell import ROOT, first_missing, give_back

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
            proc.wait()  # Ctrl-C reaches the run too; let it release everything first
            raise
        return proc.wait()


def run_session(name, bench, conditions, ns, repeats, phase=30, window=10, seed=None, dry_run=False):
    """Run benchmark `name` (config module `bench`). Return 0 when done, 1 if interrupted."""
    seed = seed if seed is not None else random.randrange(2**32)
    plan = [(c, n, k) for c in conditions for n in ns for k in range(1, repeats + 1)]
    random.Random(seed).shuffle(plan)
    per_run = 3 * phase + RUN_OVERHEAD
    print(f"{name}: {len(plan)} runs ({len(conditions)} conditions x {len(ns)} values of N x "
          f"{repeats} repeats), seed {seed}")
    print(f"Estimated time: about {duration(NOISE_SECONDS + len(plan) * per_run)}")
    if dry_run:
        for i, (c, n, k) in enumerate(plan, 1):
            print(f"  {i:>3}  {c:<4}  N={n:<5}  repeat {k}")
        return 0

    host = socket.gethostname()
    started_at = datetime.now()
    session = ROOT / "results" / name / f"session-{host}-{started_at.strftime('%Y%m%d-%H%M%S')}"
    created = first_missing(session) or session  # the folder to hand back to the sudo user at the end
    session.mkdir(parents=True)
    log = session / "runs.log"
    (session / "manifest.json").write_text(json.dumps({
        "benchmark": name,
        "host": host,
        "started": started_at.isoformat(timespec="seconds"),
        "workload": bench.WORKLOAD,
        "conditions": conditions,
        "n": ns,
        "repeats": repeats,
        "phase_s": phase,
        "window_s": window,
        "seed": seed,
        "order": [{"condition": c, "n": n, "repeat": k} for c, n, k in plan],
    }, indent=2) + "\n")
    print(f"Session folder: {session}")

    interrupted = False
    try:
        print("Recording the machine (sysinfo.sh)", flush=True)
        with open(session / "sysinfo.txt", "w") as f:
            subprocess.run([str(ROOT / "machine" / "sysinfo.sh")], stdout=f, stderr=subprocess.STDOUT)
        print(f"Measuring idle noise for {NOISE_SECONDS} s (noise_baseline.py)", flush=True)
        with open(session / "noise-baseline.txt", "w") as f:
            subprocess.run([sys.executable, str(ROOT / "machine" / "noise_baseline.py"), str(NOISE_SECONDS)],
                           stdout=f, stderr=subprocess.STDOUT)

        with open(session / "index.csv", "w", newline="") as index_file:
            index = csv.writer(index_file)
            index.writerow(INDEX_COLUMNS)

            def do_run(order, condition, n, repeat, attempt):
                folder = f"{condition}-N{n}-r{repeat}" + ("-retry" if attempt > 1 else "")
                with open(log, "a") as f:
                    f.write(f"\n===== {order}: {folder} =====\n")
                t = time.monotonic()
                started = datetime.now().isoformat(timespec="seconds")
                code = run_logged([sys.executable, str(ROOT / "run.py"), name, "--cell", condition, str(n),
                                   "--out", str(session / folder),
                                   "--phase", str(phase), "--window", str(window)], log)
                status = "ok" if code == 0 else "failed"
                index.writerow([order, condition, n, repeat, attempt, folder, status, code, started,
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
        give_back(created)
        give_back(ROOT / "computer-state")  # sysinfo.sh and noise_baseline.py also save copies there

    print("interrupted" if interrupted else "done", session)
    return 1 if interrupted else 0
