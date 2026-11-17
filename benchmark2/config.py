"""Benchmark 2: memory cost of cgroups, and whether it depends on the memory limit.

run.py reads this file. The program is build/benchmark2, started as
`build/benchmark2 <condition> <N> build/<WORKLOAD>` (see main.c).
"""

import os

from lib.procfs import child_pids, proc_state

WORKLOAD = "small"

# Must match CGROUP_PARENT in common/cgroup.h.
CGROUP_PARENT = "/sys/fs/cgroup/isolation-benchmark"

# Each condition, and what one of its N things is (for "cost per ..." in summary.txt).
# CG-<limit> sets memory.max on each empty cgroup; add more limits here to test them.
CONDITIONS = {
    "P": "process",
    "P+CG": "process",
    "CG": "cgroup",
    "CG-16M": "cgroup",
    "CG-16G": "cgroup",
}

N = [1, 10, 100, 1000]
REPEATS = 5

PAGE = os.sysconf("SC_PAGE_SIZE")


def expected_memory_max(condition):
    """What memory.max should read back as: "max", or the limit in bytes rounded down to a page."""
    if not condition.startswith("CG-"):
        return "max"
    limit = condition[3:]
    scale = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}.get(limit[-1].upper(), 1)
    number = int(limit[:-1]) if scale > 1 else int(limit)
    return str(number * scale // PAGE * PAGE)


def cgroup_of(pid):
    """Return a process's cgroup v2 path, such as "/isolation-benchmark/cg3"."""
    with open(f"/proc/{pid}/cgroup") as f:
        for line in f:
            if line.startswith("0::"):
                return line[3:].strip()
    return None


def made_cgroups():
    """Return the cgroups under CGROUP_PARENT (the N things of the CG conditions)."""
    try:
        return sorted(e.path for e in os.scandir(CGROUP_PARENT) if e.is_dir())
    except FileNotFoundError:
        return []


def checks(condition, n, pid):
    """Check, after the running window, that the program holds what it should.
    Return [(check, ok, detail)]."""
    kids = child_pids(pid)
    cgroups = made_cgroups()
    try:
        with open(f"{CGROUP_PARENT}/cgroup.subtree_control") as f:
            memory_on = "memory" in f.read().split()
    except FileNotFoundError:
        memory_on = False
    result = [("memory controller", memory_on, f"{'on' if memory_on else 'off'} for the cgroups made (expect on)")]

    if condition != "P" and condition != "P+CG":  # CG and CG-<limit>
        want = expected_memory_max(condition)
        wrong = 0
        for path in cgroups:
            with open(f"{path}/memory.max") as f:
                wrong += f.read().strip() != want
        return result + [
            ("processes", not kids, f"{len(kids)} (expect 0)"),
            ("cgroups", len(cgroups) == n, f"{len(cgroups)} made (expect {n})"),
            ("memory.max", wrong == 0, f"{wrong} cgroups without memory.max {want}"),
        ]

    driver_cgroup = cgroup_of(pid)
    places, sleeping = set(), 0
    for kid in kids:
        try:
            places.add(cgroup_of(kid))
            sleeping += proc_state(kid) == "S"
        except FileNotFoundError:
            pass
    if condition == "P":
        place_ok, place_expect = places == {driver_cgroup} and not cgroups, "all in the driver's, none made"
    else:
        prefix = CGROUP_PARENT.removeprefix("/sys/fs/cgroup") + "/"
        place_ok = len(places) == n and all(p.startswith(prefix) for p in places) and len(cgroups) == n
        place_expect = f"{n} new"
    return result + [
        ("processes", len(kids) == n, f"{len(kids)} (expect {n})"),
        ("idle", sleeping == n, f"{sleeping} sleeping (expect {n})"),
        ("cgroups", place_ok, f"{len(places)} distinct, {len(cgroups)} made (expect {place_expect})"),
    ]
