#!/usr/bin/env python3
"""One benchmark run: log memory once a second while driver holds N processes
or N network namespaces alive.

Usage: sudo ./run_cell.py <P|P+NS|NS> <N> [--out DIR] [--program PATH]
                          [--phase SECONDS] [--window SECONDS] [--interval SECONDS]

Steps (the "How one run works" section of the Measurement How-To):
  1. Start logging memory every --interval seconds (default 1).
  2. Before: wait --phase seconds (default 30) with nothing started.
  3. Start ./driver and wait for "READY N".
  4. Running: wait --phase seconds.
  5. Send SIGTERM to driver and wait for "RELEASED".
  6. After: wait --phase seconds.
  7. Stop logging and write summary.txt.

Each phase's value is the median of its last --window seconds (default 10).
Needs root: creating network namespaces and reading /proc/slabinfo both do.
driver and the program must be built first, next to this script.

Output goes to --out, or to results/<program>-<condition>-N<n>-<host>-<time>/
next to this script. All memory values are in kB.
  trace.csv    one row per sample: system and kernel memory, swap, totals over the processes
  procs.csv    one row per process per sample: pid, Pss, Rss
  slab.csv     one row per kernel cache per sample
  driver.log   everything driver printed
  summary.txt  events, phase values, cost, left behind and checks
Under sudo, the output folder is handed back to the user who ran sudo.

Exit status is 0 when the run finished and every check passed, 1 otherwise.
"""

import argparse
import csv
import os
import queue
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
DRIVER_TIMEOUT = 600  # seconds to wait for READY or RELEASED; 1000 namespaces take a while

MEMINFO_FIELDS = [
    "MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "Shmem",
    "Slab", "SReclaimable", "SUnreclaim", "KernelStack", "PageTables",
    "Percpu", "VmallocUsed", "SwapTotal", "SwapFree",
]
# Derived columns, chosen so that bigger means more memory in use:
#   SlabObjects = active objects x object size, summed over /proc/slabinfo
#   MemUsed = MemTotal - MemAvailable, SwapUsed = SwapTotal - SwapFree
#   Pss, Rss = summed over driver's children; DriverPss, DriverRss = driver itself
TRACE_COLUMNS = (
    ["t", "phase"] + MEMINFO_FIELDS
    + ["SlabObjects", "MemUsed", "SwapUsed", "Procs", "Pss", "Rss", "DriverPss", "DriverRss"]
)
# Quantities in summary.txt, by group. SlabObjects and Percpu are the main measures:
# Slab and SUnreclaim only move when a cache needs a whole new page, so they miss small changes.
GROUPS = [
    ("Kernel", ["SlabObjects", "Percpu", "VmallocUsed", "SUnreclaim", "Slab",
                "SReclaimable", "KernelStack", "PageTables"]),
    ("Processes", ["Pss", "Rss"]),
    ("System", ["MemUsed", "Cached", "SwapUsed"]),
]
REPORTED = [q for _, quantities in GROUPS for q in quantities]


class RunFailed(Exception):
    pass


def read_meminfo():
    """Return {field: kB} for MEMINFO_FIELDS, plus MemUsed and SwapUsed."""
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            name, rest = line.split(":", 1)
            if name in MEMINFO_FIELDS:
                values[name] = int(rest.split()[0])
    values["MemUsed"] = values["MemTotal"] - values["MemAvailable"]
    values["SwapUsed"] = values["SwapTotal"] - values["SwapFree"]
    return values


def read_slabinfo():
    """Return [(cache, active_objs, num_objs, objsize, kB)] for every kernel cache."""
    caches = []
    with open("/proc/slabinfo") as f:
        for line in f.readlines()[2:]:  # skip the version line and the column header
            # name active_objs num_objs objsize objperslab pagesperslab
            #   : tunables a b c : slabdata active_slabs num_slabs sharedavail
            p = line.split()
            caches.append((p[0], int(p[1]), int(p[2]), int(p[3]), int(p[14]) * int(p[5]) * PAGE_KB))
    return caches


def read_rollup(pid):
    """Return {"Pss": kB, "Rss": kB} for a process, or None if it has gone."""
    values = {}
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                name, _, rest = line.partition(":")
                if name in ("Pss", "Rss"):
                    values[name] = int(rest.split()[0])
    except (FileNotFoundError, ProcessLookupError):
        return None
    return values if len(values) == 2 else None  # a zombie has an empty file


def child_pids(pid):
    """Return the pids of a process's children ([] if it has gone)."""
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as f:
            return [int(x) for x in f.read().split()]
    except FileNotFoundError:
        return []


def net_ns(pid):
    """Return a process's network namespace, as "net:[inode]"."""
    return os.readlink(f"/proc/{pid}/ns/net")


def proc_state(pid):
    """Return a process's state letter (S = sleeping)."""
    with open(f"/proc/{pid}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[0]


class Sampler(threading.Thread):
    """Logs memory every `interval` seconds until stop() is called.

    The main thread sets `phase` and `driver_pid`; every sample is labeled with
    the phase it was taken in, and the processes logged are driver's children.
    """

    def __init__(self, outdir, interval):
        super().__init__(daemon=True)
        self.outdir = outdir
        self.interval = interval
        self.phase = "before"
        self.driver_pid = None
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
                open(self.outdir / "procs.csv", "w", newline="") as pf, \
                open(self.outdir / "slab.csv", "w", newline="") as sf:
            trace, procs, slab = csv.writer(tf), csv.writer(pf), csv.writer(sf)
            trace.writerow(TRACE_COLUMNS)
            procs.writerow(["t", "phase", "pid", "Pss", "Rss"])
            slab.writerow(["t", "phase", "cache", "active_objs", "num_objs", "objsize", "kB"])
            i = 0
            while not self.done.is_set():
                self.sample(trace, procs, slab)
                for f in (tf, pf, sf):  # flushed every sample, so a crash keeps the trace so far
                    f.flush()
                # Sleep until the next whole interval, skipping any that sampling overran.
                i = max(i + 1, int(self.now() / self.interval) + 1)
                self.done.wait(max(0.0, i * self.interval - self.now()))

    def sample(self, trace, procs, slab):
        t = round(self.now(), 3)
        phase, driver = self.phase, self.driver_pid
        row = read_meminfo()
        children = []
        if driver:
            for pid in child_pids(driver):
                r = read_rollup(pid)
                if r:
                    children.append((pid, r))
        d = read_rollup(driver) if driver else None
        caches = read_slabinfo()
        row.update(
            t=t,
            phase=phase,
            SlabObjects=round(sum(active * size for _, active, _, size, _ in caches) / 1024),
            Procs=len(children),
            Pss=sum(r["Pss"] for _, r in children),
            Rss=sum(r["Rss"] for _, r in children),
            DriverPss=d["Pss"] if d else 0,
            DriverRss=d["Rss"] if d else 0,
        )
        trace.writerow([row[c] for c in TRACE_COLUMNS])
        procs.writerows([t, phase, pid, r["Pss"], r["Rss"]] for pid, r in children)
        slab.writerows([t, phase, *c] for c in caches)
        self.rows.append(row)


def start_driver(condition, n, program, log_path):
    """Start driver. Return (process, queue of its output lines, ending with None)."""
    proc = subprocess.Popen(
        [str(SCRIPT_DIR / "driver"), condition, str(n), str(program)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
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
    """Wait for driver to print the line `expected`. Raise RunFailed if it does not."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise RunFailed(f"no '{expected}' from driver after {timeout} s (see driver.log)")
        if line is None:
            raise RunFailed(f"driver stopped before '{expected}' (see driver.log)")
        if line == expected:
            return


def check_ready(condition, n, driver_pid):
    """Check that driver holds what it should. Return [(check, ok, detail)]."""
    host_ns = net_ns("self")
    kids = child_pids(driver_pid)
    if condition == "NS":
        held = set()
        for fd in os.listdir(f"/proc/{driver_pid}/fd"):
            try:
                link = os.readlink(f"/proc/{driver_pid}/fd/{fd}")
            except FileNotFoundError:
                continue
            if link.startswith("net:"):
                held.add(link)
        return [
            ("processes", not kids, f"{len(kids)} (expect 0)"),
            ("namespaces", len(held) == n and host_ns not in held, f"{len(held)} new held by driver (expect {n})"),
        ]

    spaces, sleeping = set(), 0
    for pid in kids:
        try:
            spaces.add(net_ns(pid))
            sleeping += proc_state(pid) == "S"
        except FileNotFoundError:
            pass
    if condition == "P":
        ns_ok, ns_expect = spaces == {host_ns}, "all in the host's"
    else:
        ns_ok, ns_expect = len(spaces) == n and host_ns not in spaces, f"{n} new"
    return [
        ("processes", len(kids) == n, f"{len(kids)} (expect {n})"),
        ("idle", sleeping == n, f"{sleeping} sleeping (expect {n})"),
        ("namespaces", ns_ok, f"{len(spaces)} distinct (expect {ns_expect})"),
    ]


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


def write_summary(path, args, program, host, started_at, events, rows, checks, failure, ok):
    values = {p: phase_values(rows, p, args.window) for p in ("before", "running", "after")}
    b, r, a = values["before"], values["running"], values["after"]
    unit = "namespace" if args.condition == "NS" else "process"

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
                num(cost, "+,.0f"), num(cost / args.n if cost is not None else None, "+,.1f"),
                num(left, "+,.0f"),
            ])

    lines = [
        f"run_cell {args.condition}, N = {args.n}, program {program.name}, host {host}",
        f"Started {started_at.isoformat(timespec='seconds')}. Phases of {args.phase:g} s, "
        f"one sample every {args.interval:g} s.",
        f"Status: {'ok' if ok else 'FAILED'}" + (f" ({failure})" if failure else ""),
        "",
        "EVENTS",
        *format_table([["phase", "starts at (s)", "note"]],
                      [[phase, f"{t:.1f}", note] for phase, t, note in events], "lrl"),
        "",
        f"MEMORY (all in kB; before, running and after are medians of the last {args.window:g} s of each phase)",
        *format_table(
            [["", "before", "running", "after", "cost", "cost per", "left"],
             ["quantity", "", "", "", "", unit, "behind"]],
            memory, "lrrrrrr"),
        "",
        "  cost = running - before; cost per " + unit + f" = cost / {args.n}; left behind = after - before",
        "  SlabObjects = active objects x object size, summed over /proc/slabinfo",
        "  Pss, Rss = summed over the processes (driver not included)",
        "  MemUsed = MemTotal - MemAvailable; SwapUsed = SwapTotal - SwapFree",
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
    if uid is None or gid is None:
        return
    for folder, _, files in os.walk(path):
        os.chown(folder, int(uid), int(gid))
        for name in files:
            os.chown(os.path.join(folder, name), int(uid), int(gid))


def main():
    ap = argparse.ArgumentParser(description="One benchmark run (see the Measurement How-To).")
    ap.add_argument("condition", choices=["P", "P+NS", "NS"])
    ap.add_argument("n", type=int, help="number of processes or namespaces")
    ap.add_argument("--program", default=str(SCRIPT_DIR / "small"), help="program driver runs (default ./small)")
    ap.add_argument("--out", type=Path, help="folder for this run's files")
    ap.add_argument("--phase", type=float, default=30, help="seconds in each phase (default 30)")
    ap.add_argument("--window", type=float, default=10, help="seconds at the end of a phase to take the median over (default 10)")
    ap.add_argument("--interval", type=float, default=1, help="seconds between samples (default 1)")
    args = ap.parse_args()
    if args.n < 1:
        ap.error("N must be at least 1")
    if os.geteuid() != 0:
        sys.exit("run_cell.py needs root: sudo ./run_cell.py ...")

    program = Path(args.program).resolve()
    for path, build in [(SCRIPT_DIR / "driver", "gcc -O2 -o driver driver.c"),
                        (program, "gcc -O2 -static -o small small.c")]:
        if not os.access(path, os.X_OK):
            sys.exit(f"{path} not found; build it first: {build}")

    host = socket.gethostname()
    started_at = datetime.now()
    outdir = args.out or SCRIPT_DIR / "results" / (
        f"{program.name}-{args.condition}-N{args.n}-{host}-{started_at.strftime('%Y%m%d-%H%M%S')}")
    created = first_missing(outdir) or outdir  # the folder to hand back to the sudo user at the end
    outdir.mkdir(parents=True, exist_ok=True)

    sampler = Sampler(outdir, args.interval)
    events, checks, failure, proc = [], [], None, None

    def mark(phase, note=""):
        sampler.phase = phase
        events.append((phase, sampler.now(), note))
        print(f"[{sampler.now():7.1f} s] {phase} {note}".rstrip(), flush=True)

    sampler.start()
    mark("before")
    try:
        time.sleep(args.phase)

        mark("starting")
        proc, lines = start_driver(args.condition, args.n, program, outdir / "driver.log")
        sampler.driver_pid = proc.pid
        wait_for(lines, f"READY {args.n}", DRIVER_TIMEOUT)
        mark("running", "READY")
        checks += check_ready(args.condition, args.n, proc.pid)
        time.sleep(args.phase)

        mark("stopping")
        proc.send_signal(signal.SIGTERM)
        wait_for(lines, "RELEASED", DRIVER_TIMEOUT)
        code = proc.wait(timeout=DRIVER_TIMEOUT)
        mark("after", "RELEASED")
        checks.append(("driver exit", code == 0, f"status {code}"))
        time.sleep(args.phase)
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
    report = write_summary(outdir / "summary.txt", args, program, host, started_at,
                           events, sampler.rows, checks, failure, ok)
    give_back(created)
    print()
    print(report, end="")
    print(f"Saved to {outdir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
