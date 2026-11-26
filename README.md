# Reducing Cost of Isolation

Consolidating many isolated workloads onto a single physical host is increasingly attractive as memory becomes a dominant and rising cost in cloud deployments, but the isolation mechanisms available today impose overheads that limit achievable density. OS-level primitives such as control groups and network namespaces provide lightweight isolation, yet their provisioning and teardown are not free: bringing up a node, or recovering one after a reboot, requires constructing large numbers of cgroups and network namespaces, and at high density this setup cost becomes a significant contributor to end-to-end latency. Hardware virtualization offers stronger isolation but carries its own penalties, most acutely the cost of VMExit transitions under nested virtualization. This project characterizes the overheads of these isolation technologies as a function of density and examines the tradeoffs among isolation strength, provisioning cost, and memory footprint, with the goal of informing the design of denser single-host deployments under tightening memory budgets.
Characterization. Measure the runtime and memory overheads of candidate isolation mechanisms (network namespaces, cgroups, containers, and nested VMs) on a single host across a range of densities, establishing a baseline cost for each primitive.
Provisioning analysis. Quantify the latency of creating and tearing down isolation contexts, with particular attention to node startup and post-reboot recovery, and identify which components dominate setup time as density increases.
Virtualization overhead study. Isolate and measure the cost of VMExit transitions under nested virtualization, and compare full-virtualization isolation against OS-level alternatives on the same workloads.
Design and prototyping. Investigate mechanisms to reduce provisioning latency and per-instance memory footprint—for example, reuse or pooling of isolation contexts and deferred construction—prioritizing approaches that preserve isolation guarantees.
Evaluation. Assess the prototypes against representative workloads, reporting the tradeoffs among density, isolation strength, provisioning cost, and memory consumption.


## Layout

```
Makefile          make builds everything into build/
common/           C code shared by benchmark programs
  driver.c/.h       start N copies of a workload, READY/RELEASED protocol, hold until SIGTERM
  netns.c/.h        network namespace helpers
  cgroup.c/.h       cgroup v2 helpers (cgroups under /sys/fs/cgroup/isolation-benchmark)
workloads/        programs the benchmarks run (small.c: prints a ready line, then pause())
benchmarkN/       one folder per benchmark (1: network namespaces, 2: cgroups)
  main.c            the benchmark program, built from common/
  config.py         conditions, values of N, repeats, and checks for run.py
lib/              Python shared by every benchmark
  procfs.py         readers for /proc (meminfo, slabinfo, Pss/Rss, namespaces)
  cell.py           one run: log memory before, while and after the program holds N things
  session.py        a whole session: every condition x N, repeated, shuffled, retried
machine/          sysinfo.sh and noise_baseline.py: record the machine before a session
run.py            the one command the operator runs
analyze.py        graph one session: cost per item against N (uv run analyze.py <session> [--static])
results/          output, one folder per benchmark (not in git)
```

## Running

```
make
./run.py benchmark1 --dry-run             # run order and estimated time
sudo ./run.py benchmark1                  # whole session; run it inside tmux
sudo ./run.py benchmark1 --cell P+NS 10   # one run
```

A new benchmark is a new `benchmarkN/` folder with a `main.c` and a `config.py`.
`make` and `run.py` pick it up without other changes.
