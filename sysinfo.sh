#!/usr/bin/env bash
# Record the machine's state before a benchmark run.
# Usage: ./sysinfo.sh   (works from any directory)
# Output is always saved to computer-state/sysinfo-<hostname>-<date>-<time>.txt
# next to this script (the directory is created if needed), so start conditions
# are always logged in one place.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
outdir="$script_dir/computer-state"
mkdir -p "$outdir"
outfile="$outdir/sysinfo-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"

# Print a blank line, then a boxed header, so sections are easy to tell apart.
section() {
  echo
  echo "============================================================"
  echo "  $1"
  echo "============================================================"
}

report() {
  section "Date"
  date -Is

  section "OS and kernel"
  uname -r
  grep PRETTY_NAME /etc/os-release
  cat /proc/cmdline

  section "Virtualization"
  systemd-detect-virt

  section "CPU"
  nproc
  lscpu
  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null

  section "Memory"
  free -h
  echo
  grep -E "^(MemTotal|MemFree|MemAvailable|Buffers|Cached|Shmem|Slab|SReclaimable|SUnreclaim|KernelStack|PageTables)" /proc/meminfo
  echo
  echo "overcommit_memory: $(cat /proc/sys/vm/overcommit_memory)"
  echo "swappiness: $(cat /proc/sys/vm/swappiness)"
  echo "transparent hugepages: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"

  section "Swap (should be empty during runs)"
  cat /proc/swaps

  section "Storage"
  df -h
  echo
  lsblk

  section "cgroup version (cgroup2fs = v2)"
  stat -fc %T /sys/fs/cgroup
  cat /sys/fs/cgroup/cgroup.controllers

  section "Namespaces"
  ls /proc/self/ns
  echo
  for f in /proc/sys/user/max_*_namespaces; do echo "$f: $(cat $f)"; done

  section "Limits"
  echo "open files (ulimit -n): $(ulimit -n)"
  echo "processes (ulimit -u): $(ulimit -u)"
  echo "pid_max: $(cat /proc/sys/kernel/pid_max)"

  section "Load (should be near 0 when quiet)"
  uptime
  echo
  ps -eo pcpu,pmem,comm --sort=-pcpu | head -6

  section "Tools"
  for tool in gcc python3 perf strace; do
    command -v $tool || echo "$tool MISSING"
  done
  echo
}

report | tee "$outfile"
echo "Saved to $outfile"
