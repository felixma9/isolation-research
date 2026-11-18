/* cgroup.c: cgroup v2 helpers; see cgroup.h. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include "cgroup.h"
#include "driver.h"

static int made;        /* cgroups cg0 .. cg<made-1> exist */
static int parent_made; /* CGROUP_PARENT exists and is ours */

/* Write a string to a file such as memory.max. Returns 0, or -1 with errno set. */
static int write_file(const char *path, const char *text)
{
	int fd = open(path, O_WRONLY);
	if (fd < 0)
		return -1;
	ssize_t len = strlen(text), w = write(fd, text, len);
	int saved = errno; /* close() must not hide the write's error */
	close(fd);
	errno = saved;
	return w == len ? 0 : -1;
}

/* On an early exit (fail() or a return from main), reap any processes still
 * around, so their cgroups are empty, then remove the cgroups. */
static void cleanup_at_exit(void)
{
	if (!parent_made)
		return; /* nothing of ours left to clean up */
	while (waitpid(-1, NULL, 0) > 0)
		;
	cgroup_remove_all();
}

void cgroup_setup(void)
{
	/* Refuse to start on top of leftovers from a crashed run. */
	if (access(CGROUP_PARENT, F_OK) == 0) {
		errno = 0;
		fail(CGROUP_PARENT " already exists, left over from an earlier run; remove its "
		     "cgroups with rmdir (children first) before measuring");
	}
	/* A cgroup is a folder: mkdir creates it. */
	if (mkdir(CGROUP_PARENT, 0755) < 0)
		fail("mkdir " CGROUP_PARENT);
	parent_made = 1;
	atexit(cleanup_at_exit); /* from now on, always clean up on exit */
	/* Give every cgroup we make under the parent the memory controller. */
	if (write_file(CGROUP_PARENT "/cgroup.subtree_control", "+memory") < 0)
		fail("turn on the memory controller in " CGROUP_PARENT "/cgroup.subtree_control "
		     "(is it on in /sys/fs/cgroup/cgroup.subtree_control?)");
}

void cgroup_create(int i, const char *memory_max)
{
	char path[256];
	/* Make the folder CGROUP_PARENT/cg<i>. */
	snprintf(path, sizeof path, CGROUP_PARENT "/cg%d", i);
	if (mkdir(path, 0755) < 0)
		fail("mkdir cgroup");
	made = i + 1;
	/* Optionally set its memory limit, e.g. "16M". */
	if (memory_max) {
		snprintf(path, sizeof path, CGROUP_PARENT "/cg%d/memory.max", i);
		if (write_file(path, memory_max) < 0)
			fail("write memory.max");
	}
}

int cgroup_join(void)
{
	/* Runs in a child just before exec. Writing "0" to cgroup.procs moves the
	 * calling process; `created` is this child's number, so it joins cg<created>. */
	char path[256];
	snprintf(path, sizeof path, CGROUP_PARENT "/cg%d/cgroup.procs", created);
	if (write_file(path, "0") < 0) {
		perror(path);
		return -1;
	}
	return 0;
}

int cgroup_remove_all(void)
{
	char path[256];
	int ok = 0;
	/* rmdir each child cgroup, newest first. A cgroup can only be removed once
	 * no process is in it. */
	for (; made > 0; made--) {
		snprintf(path, sizeof path, CGROUP_PARENT "/cg%d", made - 1);
		if (rmdir(path) < 0 && errno != ENOENT) {
			perror(path);
			ok = -1;
			break; /* keep `made` so a later call can try again */
		}
	}
	/* Then the parent, once it is empty. */
	if (ok == 0 && parent_made) {
		if (rmdir(CGROUP_PARENT) < 0 && errno != ENOENT) {
			perror(CGROUP_PARENT);
			return -1;
		}
		parent_made = 0;
	}
	return ok;
}
