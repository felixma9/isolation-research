# Results

Benchmark 1 (network namespace memory cost) and Benchmark 2 (cgroup memory cost).

Bash-only runs on Cortes (64 CPUs): a logger writes /proc/meminfo and
/proc/slabinfo fields to mem.csv once a second (kB); a driver shell starts and
stops the items and writes "time,<condition> <N> start|stop|end" marks.
Run numbers match the Benchmark 1 and Benchmark 2 tabs of the team doc; Benchmark 2 folders start with b2-.

| Folder | Doc | Date | What | Layout |
|---|---|---|---|---|
| run4-unpinned-n1000-nov23/ | Run 4 | Nov 23 | P, P+NS, NS at N = 1000, not pinned | run1..3/ each with mem.csv + events.csv |
| run5-pinned-n10-3000-nov24/ | Run 5 | Nov 24 | P, P+NS, NS at N = 10, 100, 1000, 3000, driver pinned to CPU 0 | one mem.csv + events-run1..3.csv |
| run6-unpinned-n1000-nov25/ | Run 6 | Nov 25 | P, P+NS, NS at N = 1000, not pinned (control for Run 5) | one mem.csv + events-run1..3.csv |
| run7-pinned-n10000-30000-nov25/ | Run 7 | Nov 25 | P, P+NS, NS at N = 10000, 20000, 30000, driver pinned to CPU 0 (extends Run 5) | one mem.csv + events-run1..3.csv |
| b2-run1-unpinned-n100-3000-nov26/ | Benchmark 2, Run 2 | Nov 26 | P, P+CG, CG at N = 100, 1000, 3000, not pinned (benchmark2/run.sh); mem.csv has a Dying column | one mem.csv + events-run1..3.csv |

Originals on Cortes: /data/felix/manual-results (Run 4),
/data/felix/manual-results-pinned (Run 5), /data/felix/manual-results-unpinned (Run 6),
/data/felix/manual-results-pinned-large (Run 7),
/data/felix/manual-results-cgroups (Benchmark 2, Run 2).

Analysis (from the top of the repo):
- Runs 5, 6, 7 and b2-run1: `python3 analysis/pinned.py results/<folder> [out.json]`
- Run 4: `python3 analysis/manual_page.py results/run4-unpinned-n1000-nov23 out.html`,
  `uv run analysis/plot_doc.py results/run4-unpinned-n1000-nov23 SUnreclaim out.png`

Note: Run 7 (N up to 30000) finished cleanly, but Cortes lost network access around
then (systemd-networkd-wait-online timed out on Nov 26). The run scripts now refuse
N above 10000.

Runs 1 to 3 used the old Python harness (removed; see git history before this
folder was added). Their output is not in the repo.
