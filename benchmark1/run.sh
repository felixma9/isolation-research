#!/bin/bash
# benchmark1/run.sh: memory cost of network namespaces (Benchmark 1).
#
# Usage: sudo benchmark1/run.sh <out-dir> [N ...]        (default N: 1000)
#   PIN=1 sudo -E benchmark1/run.sh ...   pins the driver to CPU 0 (Runs 5 and 7).
#   Key findings say not to pin for headline numbers, so the default is unpinned.
#
# Start scripts/logger.sh <out-dir> first, in another pane. Then, for each of 3 runs:
# wait 2 minutes, and for each N, for each condition in turn:
#   start the N items, wait 2 minutes, stop them, wait 3 minutes.
# Conditions:
#   P     N processes (build/small)
#   P+NS  N processes, each started by `unshare --net` in its own network namespace
#   NS    N empty network namespaces, made with `ip netns add`
#
# Each start, stop and end is written to <out-dir>/events-run<R>.csv as
# "time,<condition> <N> start|stop|end". Analyse with analysis/pinned.py.
# One run at N = 1000 takes about 17 minutes.

set -u
OUT=${1:?usage: sudo benchmark1/run.sh <out-dir> [N ...]}
shift
N_LIST=${*:-1000}
MAX_N=10000   # Run 7 (N = 30000) was followed by Cortes losing network access

for N in $N_LIST; do
  [ "$N" -le $MAX_N ] || { echo "N = $N is above $MAX_N; refusing"; exit 1; }
done
cd "$(dirname "$0")/.." && [ -x build/small ] || { echo "build/small missing: run make"; exit 1; }
[ "$(ip netns list | grep -c '^mini')" -eq 0 ] || { echo "leftover mini* namespaces: remove them first"; exit 1; }
mkdir -p "$OUT"

if [ "${PIN:-0}" = 1 ]; then taskset -cp 0 $$; else taskset -cp 0-$(($(nproc) - 1)) $$; fi

mark() { echo "$(date +%s),$*" >> "$EV" || echo "!!! MARK FAILED"; }
P_start()    { for i in $(seq $N); do build/small >/dev/null & done; }
PNS_start()  { for i in $(seq $N); do unshare --net build/small >/dev/null & done; }
NS_start()   { for i in $(seq $N); do ip netns add mini$i; done; }
procs_stop() { kill $(jobs -p); wait; }
NS_stop()    { for i in $(seq $N); do ip netns del mini$i; done; }
one() { mark $1 $N start; $2; sleep 120; mark $1 $N stop; $3; sleep 180; mark $1 $N end; }

for RUN in 1 2 3; do
  EV=$OUT/events-run$RUN.csv
  sleep 120
  for N in $N_LIST; do
    one P P_start procs_stop
    one P+NS PNS_start procs_stop
    one NS NS_start NS_stop
  done
  echo "run $RUN done"
done
echo "all done"
