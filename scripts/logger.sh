#!/bin/bash
# logger.sh: log kernel memory once a second, for the run scripts to be measured against.
#
# Usage: sudo scripts/logger.sh <out-dir>
#   Start it first, in its own tmux pane, and leave it running; stop it with Ctrl-C
#   after the run script prints "all done".
#
# Writes <out-dir>/mem.csv, one row a second, values in kB:
#   time          seconds since 1970
#   MemAvailable, MemFree, SUnreclaim, Percpu, KernelStack, PageTables   from /proc/meminfo
#   SlabObjects   sum over /proc/slabinfo of objects in use x object size
#   Dying         cgroups removed but not yet freed by the kernel, under
#                 /sys/fs/cgroup/isolation-benchmark (0 if that folder doesn't exist)
#
# The logger runs on CPU 1, so it never shares a CPU with a driver pinned to CPU 0.

set -u
OUT=${1:?usage: sudo scripts/logger.sh <out-dir>}
CG=/sys/fs/cgroup/isolation-benchmark

taskset -cp 1 $$
mkdir -p "$OUT"
[ -s "$OUT/mem.csv" ] || echo "time,MemAvailable,MemFree,SlabObjects,SUnreclaim,Percpu,KernelStack,PageTables,Dying" > "$OUT/mem.csv"
echo "logging to $OUT/mem.csv"

while true; do
  slab=$(awk 'NR>2 {s+=$2*$4} END {printf "%d", s/1024}' /proc/slabinfo)
  dying=$(awk '/^nr_dying_descendants/ {print $2}' $CG/cgroup.stat 2>/dev/null)
  awk -v t=$(date +%s) -v s=$slab -v d=${dying:-0} '
    /^MemAvailable:/ {a=$2} /^MemFree:/ {f=$2} /^SUnreclaim:/ {u=$2}
    /^Percpu:/ {p=$2} /^KernelStack:/ {k=$2} /^PageTables:/ {pt=$2}
    END {printf "%s,%s,%s,%s,%s,%s,%s,%s,%s\n", t, a, f, s, u, p, k, pt, d}' /proc/meminfo
  sleep 1
done | tee -a "$OUT/mem.csv"
