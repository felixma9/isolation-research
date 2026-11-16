#!/usr/bin/env bash
# Record the machine's state before a benchmark run.
# Usage: machine/sysinfo.sh   (works from any directory)
# Output is always saved to computer-state/sysinfo-<hostname>-<date>-<time>.txt
# at the top of the project (the directory is created if needed), so start
# conditions are always logged in one place.

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
outdir="$root/computer-state"
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

  section "CPU settings (keep the same for every run)"
  cpu=/sys/devices/system/cpu
  # Print "label: value", or "not available" when the file does not exist (common in VMs).
  show() { echo "$1: $(cat "$2" 2>/dev/null || echo 'not available')"; }
  show "hyperthreading (smt control)" $cpu/smt/control
  show "hyperthreading active (1 = on)" $cpu/smt/active
  show "turbo off, Intel (1 = turbo off)" $cpu/intel_pstate/no_turbo
  show "turbo on, AMD/other (1 = turbo on)" $cpu/cpufreq/boost
  show "frequency driver" $cpu/cpu0/cpufreq/scaling_driver
  show "min frequency (kHz)" $cpu/cpu0/cpufreq/scaling_min_freq
  show "max frequency (kHz)" $cpu/cpu0/cpufreq/scaling_max_freq
  if [ -e $cpu/cpu0/cpufreq/scaling_governor ]; then
    echo "governor on each CPU (count governor):"
    cat $cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
  else
    echo "governor: not available"
  fi
  echo "online CPUs: $(cat $cpu/online)"

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
  for tool in gcc make python3 perf strace; do
    command -v $tool || echo "$tool MISSING"
  done
  echo
}

report | tee "$outfile"
echo "Saved to $outfile"
