#!/bin/bash
# mini.sh: Benchmarks 1 and 2 again, with as little harness as possible.
#
# A cross-check for run.py: no Python, none of our C code (common/, benchmarkN/),
# only standard tools (unshare, ip, mkdir, kill). The one thing kept the same is
# the workload, build/small, so any difference comes from the harness.
#
# Usage: sudo minimal/mini.sh <condition> <N>
#   Benchmark 1:  P      N processes
#                 P+NS   N processes, each started by `unshare --net` in a new network namespace
#                 NS     N empty network namespaces, made with `ip netns add`
#   Benchmark 2:  P+CG   N processes, each in its own new cgroup
#                 CG     N empty cgroups
#                 CG-16M N empty cgroups with memory.max 16M (any limit works)
#
# A whole session (results are appended to results/minimal/<host>.csv):
#   for r in 1 2 3; do for c in P P+NS NS P+CG CG CG-16M CG-16G; do
#     for n in 1 10 100 1000; do sudo minimal/mini.sh $c $n; done; done; done
#
# Steps, matching run.py's phases (30 s each, value = median of the last 10 s):
#   before   wait, measure         make the N things
#   running  wait, measure         check they exist, then remove them
#   after    wait, measure         print the cost and append it to the CSV
#
# Differences from run.py, on purpose:
#   - No readiness pipe: the 20 s wait before measuring covers start-up.
#   - NS uses `ip netns add`, so each namespace is held by a bind mount in
#     /run/netns (one extra small mount object each) instead of an open descriptor.
#   - Benchmark 2's parent cgroup is made before "before", so it is not in the cost.
set -eu

COND=${1:-} N=${2:-0}
case $COND in P | P+NS | NS | P+CG | CG | CG-?*) ;; *) COND="" ;; esac
if [[ -z $COND || ! $N =~ ^[1-9][0-9]*$ ]]; then
	sed -n '8,14p' "$0"
	exit 2
fi
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 2; }

HERE=$(cd "$(dirname "$0")/.." && pwd)
SMALL=$HERE/build/small     # same workload as run.py (static, prints a line, then pause())
CG=/sys/fs/cgroup/minimal   # parent of benchmark 2's cgroups
OUT=$HERE/results/minimal/$(hostname).csv
SETTLE=20                   # seconds to wait before measuring...
SAMPLES=10                  # ...then this many samples, one a second, and take the median
[[ -x $SMALL ]] || { echo "$SMALL missing: run make" >&2; exit 1; }

# One sample, in kB: MemUsed (MemTotal - MemAvailable), Percpu, SlabObjects
# (active objects x object size, summed over every kernel cache). Same definitions as run.py.
sample() {
	awk '/^MemTotal:/ {t = $2} /^MemAvailable:/ {a = $2} /^Percpu:/ {p = $2}
	     END {printf "%d %d ", t - a, p}' /proc/meminfo
	awk 'NR > 2 {s += $2 * $4} END {printf "%d\n", s / 1024}' /proc/slabinfo
}

# Wait SETTLE seconds, take SAMPLES samples, print the median of each column.
measure() {
	sleep "$SETTLE"
	local rows="" col
	for ((i = 0; i < SAMPLES; i++)); do
		rows+="$(sample)"$'\n'
		sleep 1
	done
	for col in 1 2 3; do
		printf '%s' "$rows" | awk -v c=$col '{print $c}' | sort -n |
			awk '{v[NR] = $1} END {m = NR % 2 ? v[(NR + 1) / 2] : (v[NR / 2] + v[NR / 2 + 1]) / 2; printf "%d ", m}'
	done
}

pids=()
made=0 # how many namespaces or cgroups exist (mini0 .. mini<made-1>, cg0 ..)

# Remove everything made. Safe to run twice; also runs if the script fails.
cleanup() {
	if ((${#pids[@]})); then
		kill "${pids[@]}" 2>/dev/null || true
		wait "${pids[@]}" 2>/dev/null || true
		pids=()
	fi
	if [[ $COND == NS ]]; then
		for ((i = 0; i < made; i++)); do ip netns del mini$i 2>/dev/null || true; done
	fi
	if [[ -d $CG ]]; then
		for ((i = 0; i < made; i++)); do rmdir $CG/cg$i 2>/dev/null || true; done
		rmdir $CG
	fi
	made=0
}
trap cleanup EXIT

# Benchmark 2 conditions: make the parent cgroup now, with the memory controller for its children.
if [[ $COND == *CG* ]]; then
	[[ ! -e $CG ]] || { echo "$CG left over from an earlier run: rmdir its cgroups, then it" >&2; trap - EXIT; exit 1; }
	mkdir $CG
	echo +memory >$CG/cgroup.subtree_control
fi

echo "$COND N=$N: before (${SETTLE}+${SAMPLES} s)"
before=$(measure)

echo "$COND N=$N: making $N"
start=$SECONDS
for ((i = 0; i < N; i++)); do
	case $COND in
	P) "$SMALL" >/dev/null & pids+=($!) ;;
	P+NS) unshare --net "$SMALL" >/dev/null & pids+=($!) ;; # unshare execs small: one process
	NS) ip netns add mini$i && made=$((i + 1)) ;;
	CG | CG-*)
		mkdir $CG/cg$i && made=$((i + 1))
		if [[ $COND == CG-* ]]; then echo "${COND#CG-}" >$CG/cg$i/memory.max; fi
		;;
	P+CG) # the shell moves itself into the cgroup, then becomes small (same process)
		mkdir $CG/cg$i && made=$((i + 1))
		sh -c 'echo $$ > "$1/cgroup.procs" && exec "$2"' sh $CG/cg$i "$SMALL" >/dev/null &
		pids+=($!)
		;;
	esac
done
echo "$COND N=$N: made in $((SECONDS - start)) s; running (${SETTLE}+${SAMPLES} s)"
running=$(measure)

# Check what exists, only now: looking at /proc/<pid> costs kernel memory itself.
alive=0
for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && alive=$((alive + 1)); done
case $COND in
P) check="$alive processes alive, $(for p in "${pids[@]}"; do readlink /proc/$p/ns/net; done | sort -u | wc -l) netns (expect 1)" ;;
P+NS) check="$alive processes alive, $(for p in "${pids[@]}"; do readlink /proc/$p/ns/net; done | sort -u | wc -l) distinct netns (expect $N)" ;;
NS) check="$(ls /run/netns | grep -c '^mini') netns in /run/netns" ;;
CG | CG-*) check="$(ls -d $CG/cg* | wc -l) cgroups, cg0 memory.max = $(cat $CG/cg0/memory.max)" ;;
P+CG) check="$alive processes alive, $(for p in "${pids[@]}"; do cat /proc/$p/cgroup; done | sort -u | wc -l) distinct cgroups (expect $N)" ;;
esac
echo "$COND N=$N: check: $check"

cleanup
echo "$COND N=$N: after (${SETTLE}+${SAMPLES} s)"
after=$(measure)

# Print and save.
read -r b1 b2 b3 <<<"$before"
read -r r1 r2 r3 <<<"$running"
read -r a1 a2 a3 <<<"$after"
mkdir -p "$(dirname "$OUT")"
[[ -s $OUT ]] || echo "time,condition,N,quantity,before,running,after,cost_per_item" >"$OUT"
now=$(date +%FT%T)
printf '\n%-12s %10s %10s %10s %10s %13s %12s\n' "kB" before running after cost "cost per item" "left behind"
for q in "MemUsed $b1 $r1 $a1" "Percpu $b2 $r2 $a2" "SlabObjects $b3 $r3 $a3"; do
	read -r name b r a <<<"$q"
	per=$(awk -v c=$((r - b)) -v n=$N 'BEGIN {printf "%+.1f", c / n}')
	printf '%-12s %10d %10d %10d %+10d %13s %+12d\n' "$name" "$b" "$r" "$a" $((r - b)) "$per" $((a - b))
	echo "$now,$COND,$N,$name,$b,$r,$a,$per" >>"$OUT"
done
echo "check: $check"
echo "saved to $OUT"
