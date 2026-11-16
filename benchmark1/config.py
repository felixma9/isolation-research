"""Benchmark 1: memory cost of network namespaces vs. density.

run.py reads this file. The program is build/benchmark1, started as
`build/benchmark1 <condition> <N> build/<WORKLOAD>` (see main.c).
"""

from lib.procfs import child_pids, held_namespaces, namespace, proc_state

WORKLOAD = "small"

# Each condition, and what one of its N things is (for "cost per ..." in summary.txt).
CONDITIONS = {"P": "process", "P+NS": "process", "NS": "namespace"}

N = [1, 10, 100, 1000]
REPEATS = 5


def checks(condition, n, pid):
    """Check, once READY, that the program holds what it should. Return [(check, ok, detail)]."""
    host_ns = namespace("self")
    kids = child_pids(pid)
    if condition == "NS":
        held = held_namespaces(pid)
        return [
            ("processes", not kids, f"{len(kids)} (expect 0)"),
            ("namespaces", len(held) == n and host_ns not in held, f"{len(held)} new held (expect {n})"),
        ]

    spaces, sleeping = set(), 0
    for kid in kids:
        try:
            spaces.add(namespace(kid))
            sleeping += proc_state(kid) == "S"
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
