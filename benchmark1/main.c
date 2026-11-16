/* benchmark1: memory cost of network namespaces (Benchmark 1).
 *
 * Usage: sudo build/benchmark1 <P|P+NS|NS> <N> [program]   (program defaults to build/small)
 *
 *   P      N processes in the host's network namespace
 *   P+NS   N processes, each in its own new network namespace
 *   NS     N empty network namespaces, no processes
 *
 * Prints "READY N" once all N exist, then holds them until SIGTERM (see driver.h).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver.h"
#include "netns.h"

int main(int argc, char **argv)
{
	const char *mode = argc > 2 ? argv[1] : "";
	int count = argc > 2 ? atoi(argv[2]) : 0;
	if ((strcmp(mode, "P") && strcmp(mode, "P+NS") && strcmp(mode, "NS")) || count < 1) {
		fprintf(stderr, "usage: %s <P|P+NS|NS> <N> [program]\n", argv[0]);
		return 2;
	}
	const char *program = argc > 3 ? argv[3] : "build/small";

	driver_init(count);
	if (!strcmp(mode, "NS"))
		for (created = 0; created < n; created++)
			netns_hold();
	else
		spawn_n(program, !strcmp(mode, "P+NS") ? netns_enter : NULL);
	hold();
	release();
	return 0;
}
