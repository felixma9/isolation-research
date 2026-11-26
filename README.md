# Reducing Cost of Isolation

Consolidating many isolated workloads onto a single physical host is increasingly attractive as memory becomes a dominant and rising cost in cloud deployments, but the isolation mechanisms available today impose overheads that limit achievable density. OS-level primitives such as control groups and network namespaces provide lightweight isolation, yet their provisioning and teardown are not free: bringing up a node, or recovering one after a reboot, requires constructing large numbers of cgroups and network namespaces, and at high density this setup cost becomes a significant contributor to end-to-end latency. Hardware virtualization offers stronger isolation but carries its own penalties, most acutely the cost of VMExit transitions under nested virtualization. This project characterizes the overheads of these isolation technologies as a function of density and examines the tradeoffs among isolation strength, provisioning cost, and memory footprint, with the goal of informing the design of denser single-host deployments under tightening memory budgets.
Characterization. Measure the runtime and memory overheads of candidate isolation mechanisms (network namespaces, cgroups, containers, and nested VMs) on a single host across a range of densities, establishing a baseline cost for each primitive.
Provisioning analysis. Quantify the latency of creating and tearing down isolation contexts, with particular attention to node startup and post-reboot recovery, and identify which components dominate setup time as density increases.
Virtualization overhead study. Isolate and measure the cost of VMExit transitions under nested virtualization, and compare full-virtualization isolation against OS-level alternatives on the same workloads.
Design and prototyping. Investigate mechanisms to reduce provisioning latency and per-instance memory footprint—for example, reuse or pooling of isolation contexts and deferred construction—prioritizing approaches that preserve isolation guarantees.
Evaluation. Assess the prototypes against representative workloads, reporting the tradeoffs among density, isolation strength, provisioning cost, and memory consumption.


## Layout

```
workloads/small.c     the program every benchmark runs: prints a line, then sleeps until killed
Makefile              make builds it into build/small
scripts/logger.sh     logs kernel memory from /proc once a second to <out-dir>/mem.csv
scripts/sysinfo.sh    records the machine's state before a run (to computer-state/)
benchmark1/run.sh     network namespaces: P, P+NS and NS at each N, 3 runs
benchmark2/run.sh     cgroups: P, P+CG and CG at each N, 3 runs
analysis/pinned.py    cost per item from mem.csv and the events files
analysis/*.py         older plots and pages used for Run 4 in the team doc
results/              every run in the team doc, one folder each (see results/README.md)
```

Everything is plain bash and standard tools (`unshare`, `ip netns`, `mkdir` in
cgroupfs, `kill`). There is no harness: the logger and the run script are two
separate processes, so the measuring never touches the things being measured.

## Running (on Cortes, as root, in tmux)

```
make
# Pane 1: the logger. Leave it running.
sudo scripts/logger.sh /data/felix/<out-dir>
# Pane 2: the benchmark, with the values of N to run (at most 10000).
sudo benchmark1/run.sh /data/felix/<out-dir> 1000 3000
# Afterwards (Ctrl-C the logger once "all done" prints):
python3 analysis/pinned.py /data/felix/<out-dir> > costs.json
```

Then copy the output folder into `results/` and add a row to `results/README.md`.
Keep N at or below 10000 on Cortes; the run scripts refuse anything higher.
