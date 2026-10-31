#!/usr/bin/env python3
"""Measure how much memory, load and CPU use fluctuate on an idle machine.

Usage: ./noise_baseline.py [duration_seconds]   (default 60)

Run it after Pre-run steps 1 to 5 of the Measurement How-To. It only reads
/proc, starts no other programs and changes nothing. The summary is printed and
saved to computer-state/noise-baseline-<hostname>-<date>-<time>.txt next to
this script.
"""

import os
import socket
import statistics
import sys
import time
from datetime import datetime

MEMINFO_FIELDS = ["MemAvailable", "MemFree", "Slab", "SUnreclaim", "KernelStack", "PageTables"]
QUANTITIES = MEMINFO_FIELDS + ["load1", "cpu_busy_pct"]


def read_meminfo():
    """Return {field: kB} for the fields we track."""
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            name, rest = line.split(":", 1)
            if name in MEMINFO_FIELDS:
                values[name] = int(rest.split()[0])
    return values


def read_load1():
    """Return the 1-minute load average."""
    with open("/proc/loadavg") as f:
        return float(f.read().split()[0])


def read_cpu_times():
    """Return (busy, total) jiffies summed over all cores."""
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    # Order: user nice system idle iowait irq softirq steal guest guest_nice.
    # guest and guest_nice are already counted inside user and nice, so leave them out.
    total = sum(fields[:8])
    idle = fields[3] + fields[4]  # idle + iowait
    return total - idle, total


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    if duration < 2:
        sys.exit("duration must be at least 2 seconds")

    samples = {name: [] for name in QUANTITIES}
    prev_busy, prev_total = read_cpu_times()
    start = time.monotonic()
    started_at = datetime.now()

    # One reading per second. The first reading above only gives the CPU baseline.
    for i in range(1, duration + 1):
        time.sleep(max(0.0, start + i - time.monotonic()))
        busy, total = read_cpu_times()
        samples["cpu_busy_pct"].append(100.0 * (busy - prev_busy) / max(1, total - prev_total))
        prev_busy, prev_total = busy, total
        for name, value in read_meminfo().items():
            samples[name].append(value)
        samples["load1"].append(read_load1())

    lines = [
        f"Noise baseline on {socket.gethostname()}",
        f"Started {started_at.isoformat(timespec='seconds')}, {duration} samples at 1 per second",
        "Memory values in kB; load1 is the 1-minute load average; cpu_busy_pct is % of all cores",
        "",
        f"{'quantity':<14}{'min':>12}{'max':>12}{'range':>12}{'mean':>14}{'stdev':>12}{'drift':>12}",
    ]
    for name in QUANTITIES:
        v = samples[name]
        lines.append(
            f"{name:<14}{min(v):>12.2f}{max(v):>12.2f}{max(v) - min(v):>12.2f}"
            f"{statistics.mean(v):>14.2f}{statistics.stdev(v):>12.2f}{v[-1] - v[0]:>12.2f}"
        )
    report = "\n".join(lines) + "\n"
    print(report, end="")

    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "computer-state")
    os.makedirs(outdir, exist_ok=True)
    outfile = os.path.join(
        outdir, f"noise-baseline-{socket.gethostname()}-{started_at.strftime('%Y%m%d-%H%M%S')}.txt"
    )
    with open(outfile, "w") as f:
        f.write(report)
    print(f"Saved to {outfile}")


if __name__ == "__main__":
    main()
