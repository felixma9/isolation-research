"""Readers for /proc, shared by every benchmark. All memory values are in kB."""

import os

PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024

MEMINFO_FIELDS = [
    "MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "Shmem",
    "Slab", "SReclaimable", "SUnreclaim", "KernelStack", "PageTables",
    "Percpu", "VmallocUsed", "SwapTotal", "SwapFree",
]


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
    """Return [(cache, active_objs, num_objs, objsize, kB)] for every kernel cache. Needs root."""
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


def proc_state(pid):
    """Return a process's state letter (S = sleeping)."""
    with open(f"/proc/{pid}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[0]


def namespace(pid, kind="net"):
    """Return the namespace a process is in, as "net:[inode]"."""
    return os.readlink(f"/proc/{pid}/ns/{kind}")


def held_namespaces(pid, kind="net"):
    """Return the set of namespaces a process holds open descriptors to."""
    held = set()
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            link = os.readlink(f"/proc/{pid}/fd/{fd}")
        except FileNotFoundError:
            continue
        if link.startswith(f"{kind}:"):
            held.add(link)
    return held
