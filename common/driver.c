/* driver.c: shared code for benchmark programs; see driver.h. */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "driver.h"

int n, created;
static pid_t *pids; /* processes started by spawn_n(), 0 where none */
static sigset_t sigs;

void fail(const char *what)
{
	/* Say what went wrong and how far we got. */
	fprintf(stderr, "%s (%d of %d created)%s%s\n", what, created, n, errno ? ": " : "",
		errno ? strerror(errno) : "");
	/* Kill anything already started, so nothing is left running. */
	for (int i = 0; pids && i < n; i++)
		if (pids[i] > 0)
			kill(pids[i], SIGKILL);
	exit(1);
}

void driver_init(int count)
{
	n = count;
	/* One slot per process we may start. */
	pids = calloc(n, sizeof *pids);
	if (!pids)
		fail("calloc");

	/* A namespace is held open by one descriptor, so allow n plus some spare. */
	struct rlimit rl = { n + 64, n + 64 };
	if (setrlimit(RLIMIT_NOFILE, &rl) < 0)
		fail("setrlimit");

	/* Blocked here, picked up with sigwait() in hold(). */
	sigemptyset(&sigs);
	sigaddset(&sigs, SIGTERM);
	sigaddset(&sigs, SIGINT);
	sigprocmask(SIG_BLOCK, &sigs, NULL);
}

void spawn_n(const char *program, int (*before_exec)(void))
{
	/* One pipe shared by all children: each writes a line on it when ready. */
	int p[2];
	if (pipe(p) < 0)
		fail("pipe");

	/* Start the n children, one at a time. */
	for (created = 0; created < n; created++) {
		pid_t pid = fork();
		if (pid < 0)
			fail("fork");
		if (pid == 0) {
			/* Child: set up, then turn into `program`. */
			dup2(p[1], 1); /* the program's stdout is the readiness pipe */
			close(p[0]);
			close(p[1]);
			sigprocmask(SIG_UNBLOCK, &sigs, NULL); /* so SIGTERM stops it */
			if (before_exec && before_exec() < 0) /* e.g. enter a namespace or cgroup */
				_exit(1);
			execl(program, program, (char *)NULL);
			perror(program); /* only reached if exec failed */
			_exit(1);
		}
		/* Parent: remember the child so release() can stop it. */
		pids[created] = pid;
	}
	close(p[1]); /* only the children write to the pipe */

	/* Each program writes one line when ready; wait for n lines. */
	int lines = 0;
	char buf[4096];
	while (lines < n) {
		struct pollfd pf = { p[0], POLLIN, 0 };
		if (poll(&pf, 1, 1000) == 0) { /* quiet for 1 s: check nothing went wrong */
			struct timespec zero = { 0, 0 };
			/* A child died before saying it was ready. */
			if (waitpid(-1, NULL, WNOHANG) > 0) {
				errno = 0;
				fail("a process exited before it was ready");
			}
			/* We were told to stop while still starting up. */
			if (sigtimedwait(&sigs, NULL, &zero) > 0) {
				errno = 0;
				fail("interrupted before READY");
			}
			continue;
		}
		/* Count the newlines that arrived: one per ready child. */
		ssize_t r = read(p[0], buf, sizeof buf);
		if (r <= 0) {
			errno = r < 0 ? errno : 0;
			fail("readiness pipe closed early");
		}
		for (ssize_t i = 0; i < r; i++)
			lines += buf[i] == '\n';
	}
	close(p[0]);
}

void hold(void)
{
	/* Tell run.py everything exists, then sleep until SIGTERM or Ctrl-C. */
	printf("READY %d\n", n);
	fflush(stdout);
	int sig;
	sigwait(&sigs, &sig);
}

void release(void)
{
	/* Ask every child to stop... */
	for (int i = 0; i < n; i++)
		if (pids[i] > 0)
			kill(pids[i], SIGTERM);
	/* ...and wait until each one is gone. */
	for (int i = 0; i < n; i++)
		if (pids[i] > 0)
			waitpid(pids[i], NULL, 0);
	/* Descriptors (such as held namespaces) close when the program exits. Their
	 * memory comes back a little later; run.py's "after" phase waits for it. */
	printf("RELEASED\n");
	fflush(stdout);
}
