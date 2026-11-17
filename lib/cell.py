"""One run (a "cell"): log memory once a second while a benchmark program holds
N things alive. Started by run.py; works the same for every benchmark.

Steps (the "How one run works" section of the Measurement How-To):
  1. Start logging memory every `interval` seconds.
  2. Before: wait `phase` seconds with nothing started.
  3. Start build/<benchmark> <condition> <N> build/<workload>, wait for "READY N".
  4. Running: wait `phase` seconds.
  5. Checking: run the benchmark's checks and read each process's Pss and Rss, once.
  6. Send SIGTERM and wait for "RELEASED".
  7. After: wait `phase` seconds.
  8. Stop logging and write summary.txt.

Each phase's value is the median of its last `window` seconds.

The logging only reads /proc/meminfo and /proc/slabinfo, never a process's own
/proc files: the first look at /proc/<pid> makes the kernel cache entries for it
(about 5 kB per process), which would be counted as cost. Everything that looks
at the processes waits for step 5, after the running window.

Files written to the run's folder (all memory values in kB):
  trace.csv    one row per sample: system and kernel memory, swap
  procs.csv    one row per process, read once in step 5: pid, Pss, Rss
  slab.csv     one row per kernel cache per sample
  driver.log   everything the benchmark program printed
  summary.txt  events, phase values, cost, left behind and checks
"""

import csv
import os
import queue
import signal
import socket
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from lib.procfs import MEMINFO_FIELDS, child_pids, read_meminfo, read_rollup, read_slabinfo

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DRIVER_TIMEOUT = 600  # seconds to wait for READY or RELEASED; 1000 namespaces take a while

# Derived columns, chosen so that bigger means more memory in use:
#   SlabObjects = active objects x object size, summed over /proc/slabinfo
#   MemUsed = MemTotal - MemAvailable, SwapUsed = SwapTotal - SwapFree
TRACE_COLUMNS = ["t", "phase"] + MEMINFO_FIELDS + ["SlabObjects", "MemUsed", "SwapUsed"]
# Quantities in summary.txt, by group. SlabObjects and Percpu are the main measures:
# Slab and SUnreclaim only move when a cache needs a whole new page, so they miss small changes.
GROUPS = [
    ("Kernel", ["SlabObjects", "Percpu", "VmallocUsed", "SUnreclaim", "Slab",
                "SReclaimable", "KernelStack", "PageTables"]),
    ("System", ["MemUsed", "Cached", "SwapUsed"]),
]
REPORTED = [q for _, quantities in GROUPS for q in quantities]


class RunFailed(Exception):
    pass


class Sampler(threading.Thread):
    """Logs system memory every `interval` seconds until stop() is called.

    The main thread sets `phase`; every sample is labeled with the phase it was taken in.
    """

    def __init__(self, outdir, interval):
        super().__init__(daemon=True)
        self.outdir = outdir
        self.interval = interval
        self.phase = "before"
        self.rows = []
        self.t0 = time.monotonic()
        self.done = threading.Event()

    def now(self):
        return time.monotonic() - self.t0

    def stop(self):
        self.done.set()
        self.join()

    def run(self):
        with open(self.outdir / "trace.csv", "w", newline="") as tf, \
                open(self.outdir / "slab.csv", "w", newline="") as sf:
            trace, slab = csv.writer(tf), csv.writer(sf)
            trace.writerow(TRACE_COLUMNS)
            slab.writerow(["t", "phase", "cache", "active_objs", "num_objs", "objsize", "kB"])
            i = 0
            while not self.done.is_set():
                self.sample(trace, slab)
                for f in (tf, sf):  # flushed every sample, so a crash keeps the trace so far
                    f.flush()
                # Sleep until the next whole interval, skipping any that sampling overran.
                i = max(i + 1, int(self.now() / self.interval) + 1)
                self.done.wait(max(0.0, i * self.interval - self.now()))

    def sample(self, trace, slab):
        t = round(self.now(), 3)
        phase = self.phase
        row = read_meminfo()
        caches = read_slabinfo()
        row.update(t=t, phase=phase,
                   SlabObjects=round(sum(active * size for _, active, _, size, _ in caches) / 1024))
        trace.writerow([row[c] for c in TRACE_COLUMNS])
        slab.writerows([t, phase, *c] for c in caches)
        self.rows.append(row)


def read_processes(driver_pid, path):
    """Write each of the driver's children's Pss and Rss to `path`. Return (count, Pss, Rss) totals."""
    rows = []
    for pid in child_pids(driver_pid):
        r = read_rollup(pid)
        if r:
            rows.append([pid, r["Pss"], r["Rss"]])
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["pid", "Pss", "Rss"])
        out.writerows(rows)
    return len(rows), sum(r[1] for r in rows), sum(r[2] for r in rows)


def start_driver(cmd, log_path):
    """Start the benchmark program. Return (process, queue of its output lines, ending with None)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = queue.Queue()

    def pump():  # copy each line to driver.log and hand it to the main thread
        with open(log_path, "w") as log:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                lines.put(line.strip())
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return proc, lines


def wait_for(lines, expected, timeout):
    """Wait for the program to print the line `expected`. Raise RunFailed if it does not."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise RunFailed(f"no '{expected}' after {timeout} s (see driver.log)")
        if line is None:
            raise RunFailed(f"program stopped before '{expected}' (see driver.log)")
        if line == expected:
            return


def phase_values(rows, phase, window):
    """Median of each REPORTED quantity over the last `window` seconds of a phase, or None."""
    rows = [r for r in rows if r["phase"] == phase]
    if not rows:
        return None
    end = rows[-1]["t"]
    return {q: statistics.median(r[q] for r in rows if r["t"] > end - window) for q in REPORTED}


def format_table(header_rows, rows, align):
    """Lay out rows of strings in columns, with a rule under the header rows.

    `align` has one letter per column: "l" for left-aligned, "r" for right-aligned.
    """
    widths = [max(len(r[i]) for r in header_rows + rows) for i in range(len(align))]

    def line(r):
        return "  ".join(c.ljust(w) if a == "l" else c.rjust(w)
                         for c, w, a in zip(r, widths, align)).rstrip()

    return ([line(r) for r in header_rows] + ["  ".join("-" * w for w in widths)]
            + [line(r) for r in rows])


def write_summary(path, title, n, unit, phase, window, interval, events, rows, processes, checks,
                  failure, ok):
    values = {p: phase_values(rows, p, window) for p in ("before", "running", "after")}
    b, r, a = values["before"], values["running"], values["after"]

    def num(x, fmt):
        return format(x, fmt) if x is not None else "-"

    memory = []
    for group, quantities in GROUPS:
        memory.append([group] + [""] * 6)
        for q in quantities:
            cost = r[q] - b[q] if b and r else None
            left = a[q] - b[q] if b and a else None
            memory.append([
                f"  {q}",
                num(b and b[q], ",.0f"), num(r and r[q], ",.0f"), num(a and a[q], ",.0f"),
                num(cost, "+,.0f"), num(cost / n if cost is not None else None, "+,.1f"),
                num(left, "+,.0f"),
            ])

    lines = [
        title,
        f"Phases of {phase:g} s, one sample every {interval:g} s.",
        f"Status: {'ok' if ok else 'FAILED'}" + (f" ({failure})" if failure else ""),
        "",
        "EVENTS",
        *format_table([["phase", "starts at (s)", "note"]],
                      [[p, f"{t:.1f}", note] for p, t, note in events], "lrl"),
        "",
        f"MEMORY (all in kB; before, running and after are medians of the last {window:g} s of each phase)",
        *format_table(
            [["", "before", "running", "after", "cost", "cost per", "left"],
             ["quantity", "", "", "", "", unit, "behind"]],
            memory, "lrrrrrr"),
        "",
        "  cost = running - before; cost per " + unit + f" = cost / {n}; left behind = after - before",
        "  SlabObjects = active objects x object size, summed over /proc/slabinfo",
        "  MemUsed = MemTotal - MemAvailable; SwapUsed = SwapTotal - SwapFree",
        "",
        "PROCESSES (read once, after the running window; the benchmark program itself not included)",
        (f"  {processes[0]} processes: Pss {processes[1]:,} kB ({processes[1] / processes[0]:,.1f} per process), "
         f"Rss {processes[2]:,} kB ({processes[2] / processes[0]:,.1f} per process)"
         if processes and processes[0] else "  none"),
        "",
        "CHECKS",
        *format_table([["check", "result", "detail"]],
                      [[name, "ok" if good else "FAIL", detail] for name, good, detail in checks], "lll"),
    ]
    report = "\n".join(lines) + "\n"
    path.write_text(report)
    return report


def first_missing(path):
    """Return the topmost folder in `path` that does not exist yet, or None if it all exists."""
    missing = None
    while not path.exists():
        missing, path = path, path.parent
    return missing


def give_back(path):
    """Under sudo, hand a folder and everything in it to the user who ran sudo."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid is None or gid is None or not path.exists():
        return
    for folder, _, files in os.walk(path):
        os.chown(folder, int(uid), int(gid))
        for name in files:
            os.chown(os.path.join(folder, name), int(uid), int(gid))


def run_cell(name, bench, condition, n, outdir, phase=30, window=10, interval=1):
    """Do one run of benchmark `name` (config module `bench`). Return True if every check passed."""
    host = socket.gethostname()
    started_at = datetime.now()
    created = first_missing(outdir) or outdir  # the folder to hand back to the sudo user at the end
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [str(BUILD / name), condition, str(n), str(BUILD / bench.WORKLOAD)]

    sampler = Sampler(outdir, interval)
    events, checks, failure, proc, processes = [], [], None, None, None

    def mark(p, note=""):
        sampler.phase = p
        events.append((p, sampler.now(), note))
        print(f"[{sampler.now():7.1f} s] {p} {note}".rstrip(), flush=True)

    sampler.start()
    mark("before")
    try:
        time.sleep(phase)

        mark("starting")
        proc, lines = start_driver(cmd, outdir / "driver.log")
        wait_for(lines, f"READY {n}", DRIVER_TIMEOUT)
        mark("running", "READY")
        time.sleep(phase)

        # Only now look at the processes (see the top of this file).
        mark("checking")
        checks += bench.checks(condition, n, proc.pid)
        processes = read_processes(proc.pid, outdir / "procs.csv")

        mark("stopping")
        proc.send_signal(signal.SIGTERM)
        wait_for(lines, "RELEASED", DRIVER_TIMEOUT)
        code = proc.wait(timeout=DRIVER_TIMEOUT)
        mark("after", "RELEASED")
        checks.append(("exit", code == 0, f"status {code}"))
        time.sleep(phase)
    except RunFailed as e:
        failure = str(e)
    except KeyboardInterrupt:
        failure = "interrupted"
    finally:
        mark("end")
        if proc and proc.poll() is None:  # never leave processes or namespaces behind
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
        sampler.stop()

    swap = [r["SwapUsed"] for r in sampler.rows]
    swing = max(swap) - min(swap) if swap else 0
    checks.append(("swap", swing == 0, f"swap use moved by {swing} kB during the run (expect 0)"))

    ok = failure is None and all(good for _, good, _ in checks)
    title = (f"{name} {condition}, N = {n}, workload {bench.WORKLOAD}, host {host}, "
             f"started {started_at.isoformat(timespec='seconds')}")
    report = write_summary(outdir / "summary.txt", title, n, bench.CONDITIONS[condition],
                           phase, window, interval, events, sampler.rows, processes, checks, failure, ok)
    give_back(created)
    print()
    print(report, end="")
    print(f"Saved to {outdir}")
    return ok
