/* cgroup.h: cgroup v2 helpers. Need root.
 *
 * Every cgroup a benchmark makes goes under one parent, CGROUP_PARENT, with the
 * memory controller turned on for its children. The parent is created by
 * cgroup_setup() and removed, with everything in it, by cgroup_remove_all().
 * If the program fails or exits early, the cgroups are still removed (atexit).
 */
#ifndef CGROUP_H
#define CGROUP_H

/* Keep in sync with CGROUP_PARENT in the benchmark's config.py. Can be changed
 * with -DCGROUP_PARENT=... to test without root in a delegated cgroup. */
#ifndef CGROUP_PARENT
#define CGROUP_PARENT "/sys/fs/cgroup/isolation-benchmark"
#endif

/* Create CGROUP_PARENT and turn on the memory controller for its children.
 * Fails if CGROUP_PARENT already exists (left over from an earlier run):
 * removing it here would free memory in the middle of a measurement. */
void cgroup_setup(void);

/* Create CGROUP_PARENT/cg<i>. If memory_max is not NULL, write it to the
 * cgroup's memory.max (such as "16M", "1G" or "max"). Calls fail() on error. */
void cgroup_create(int i, const char *memory_max);

/* Move the calling process into CGROUP_PARENT/cg<created>. For spawn_n()'s
 * before_exec, where `created` is the index of the child being started.
 * Returns -1 after printing an error. */
int cgroup_join(void);

/* Remove every cgroup made by cgroup_create(), then CGROUP_PARENT. Call once
 * the processes in them have been reaped. Returns 0, or -1 after printing an
 * error. Safe to call more than once. */
int cgroup_remove_all(void);

#endif
