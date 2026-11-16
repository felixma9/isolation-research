/* netns.c: network namespace helpers; see netns.h. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>

#include "driver.h"
#include "netns.h"

int netns_enter(void)
{
	if (unshare(CLONE_NEWNET) < 0) {
		perror("unshare");
		return -1;
	}
	return 0;
}

void netns_hold(void)
{
	/* unshare() moves this process into the new namespace; the descriptor keeps
	 * it alive after the next unshare() moves the process on. */
	if (unshare(CLONE_NEWNET) < 0)
		fail("unshare");
	if (open("/proc/self/ns/net", O_RDONLY) < 0)
		fail("open namespace descriptor");
}
