#!/bin/bash
# benchmark2/run.sh: memory cost of cgroups (Benchmark 2). Same method as benchmark1/run.sh.
#
# Usage: sudo benchmark2/run.sh <out-dir> [N ...]        (default N: 100 1000 3000)
#   Not pinned. Start scripts/logger.sh <out-dir> first, in another pane.
#
# Every cgroup is made under /sys/fs/cgroup/isolation-benchmark, with the memory
# controller on. That parent is made once and kept, so it isn't in any cost.
# Conditions:
#   P     N processes (build/small) in the driver's own cgroup
#   P+CG  N processes, each moved into its own new cgroup right after it starts
#   CG    N empty cgroups
#
# For each of 3 runs: wait 2 minutes, and for each N, for each condition in turn:
#   start the N items, wait 2 minutes, stop them, wait 3 minutes.
# Marks go to <out-dir>/events-run<R>.csv; analyse with analysis/pinned.py.
# The logger's Dying column should be back to 0 by each end mark.
# One run at N = 100, 1000 and 3000 takes about 50 minutes.

set -u
OUT=${1:?usage: sudo benchmark2/run.sh <out-dir> [N ...]}
shift
N_LIST=${*:-100 1000 3000}
MAX_N=10000
CG=/sys/fs/cgroup/isolation-benchmark

for N in $N_LIST; do
  [ "$N" -le $MAX_N ] || { echo "N = $N is above $MAX_N; refusing"; exit 1; }
done
cd "$(dirname "$0")/.." && [ -x build/small ] || { echo "build/small missing: run make"; exit 1; }
[ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || { echo "cgroup v2 not mounted"; exit 1; }
grep -qw memory /sys/fs/cgroup/cgroup.subtree_control || { echo "memory controller is off at the root"; exit 1; }
mkdir -p $CG && echo +memory > $CG/cgroup.subtree_control
[ "$(ls $CG | grep -c '^cg')" -eq 0 ] || { echo "leftover cgroups in $CG: remove them first"; exit 1; }
mkdir -p "$OUT"
taskset -cp 0-$(($(nproc) - 1)) $$

mark() { echo "$(date +%s),$*" >> "$EV" || echo "!!! MARK FAILED"; }
P_start()    { for i in $(seq $N); do build/small >/dev/null & done; }
PCG_start()  { for i in $(seq $N); do mkdir $CG/cg$i; build/small >/dev/null & echo $! > $CG/cg$i/cgroup.procs; done; }
CG_start()   { for i in $(seq $N); do mkdir $CG/cg$i; done; }
procs_stop() { kill $(jobs -p); wait; }
PCG_stop()   { procs_stop; rmdir $CG/cg*; }
CG_stop()    { rmdir $CG/cg*; }
one() { mark $1 $N start; $2; sleep 120; mark $1 $N stop; $3; sleep 180; mark $1 $N end; }

for RUN in 1 2 3; do
  EV=$OUT/events-run$RUN.csv
  sleep 120
  for N in $N_LIST; do
    one P P_start procs_stop
    one P+CG PCG_start PCG_stop
    one CG CG_start CG_stop
  done
  echo "run $RUN done"
done
echo "all done"
