/* benchmark2: memory cost of cgroups (Benchmark 2).
 *
 * Usage: sudo build/benchmark2 <P|P+CG|CG|CG-<limit>> <N> [program]   (program defaults to build/small)
 *
 *   P          N processes in the driver's own cgroup
 *   P+CG       N processes, each in its own new cgroup (memory controller on, no limit)
 *   CG         N empty cgroups (memory controller on, no limit)
 *   CG-<limit> N empty cgroups with memory.max set to <limit>, such as CG-16M or CG-16G
 *
 * Every condition first makes one parent cgroup (see cgroup.h), so the
 * conditions differ only in the N things. Prints "READY N" once all N exist,
 * then holds them until SIGTERM (see driver.h). The cgroups are removed on exit.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../common/cgroup.h"
#include "../common/driver.h"

int main(int argc, char **argv)
{
	/* Read the arguments: condition (with an optional limit) and N. */
	const char *mode = argc > 2 ? argv[1] : "";
	int count = argc > 2 ? atoi(argv[2]) : 0;
	int empty = !strcmp(mode, "CG") || !strncmp(mode, "CG-", 3); /* no processes */
	if ((strcmp(mode, "P") && strcmp(mode, "P+CG") && !empty) || !strcmp(mode, "CG-") || count < 1) {
		fprintf(stderr, "usage: %s <P|P+CG|CG|CG-<limit>> <N> [program]\n", argv[0]);
		return 2;
	}
	const char *program = argc > 3 ? argv[3] : "build/small";
	const char *limit = !strncmp(mode, "CG-", 3) ? mode + 3 : NULL; /* "CG-16M" -> "16M" */

	driver_init(count);
	cgroup_setup(); /* the parent cgroup, made in every condition */

	/* CG and CG-<limit>: N empty cgroups, nothing else. */
	if (empty) {
		for (created = 0; created < n; created++)
			cgroup_create(created, limit);
		hold();
		/* No processes in them, so they can go before RELEASED is printed. */
		if (cgroup_remove_all() < 0)
			return 1;
		release();
		return 0;
	}

	/* P+CG: make N cgroups, then start N processes, one in each. P: just the processes. */
	if (!strcmp(mode, "P+CG")) {
		for (created = 0; created < n; created++)
			cgroup_create(created, NULL);
		spawn_n(program, cgroup_join); /* child number `created` joins cg<created> */
	} else {
		spawn_n(program, NULL);
	}
	hold();
	release(); /* the processes must be gone before their cgroups can be removed */
	return cgroup_remove_all() < 0 ? 1 : 0;
}
