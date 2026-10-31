/* driver.c: holds N processes or N network namespaces alive while memory
 * snapshots are taken (the "During the run" steps of the Measurement How-To).
 *
 * Usage: sudo ./driver <P|P+NS|NS> <N> [program]     (program defaults to ./small)
 *
 *   P      N processes in the host's network namespace
 *   P+NS   N processes, each in its own new network namespace
 *   NS     N empty network namespaces, no processes
 *
 * Prints "READY N" once all N exist. For P and P+NS that means each process
 * has written its readiness line, so it is running the program.
 * On SIGTERM or Ctrl-C it releases everything and prints "RELEASED". Memory
 * for released namespaces comes back a little later; the How-To waits for it.
 * On any failure it stops, says which step failed, exits non-zero, and never
 * prints READY. Needs root (CLONE_NEWNET needs CAP_SYS_ADMIN).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int n, created;
static pid_t *pids;

static void fail(const char *what)
{
	fprintf(stderr, "driver: %s (%d of %d created)%s%s\n", what, created, n, errno ? ": " : "",
		errno ? strerror(errno) : "");
	for (int i = 0; i < n; i++)
		if (pids[i] > 0)
			kill(pids[i], SIGKILL);
	exit(1);
}

int main(int argc, char **argv)
{
	if (argc < 3 || (strcmp(argv[1], "P") && strcmp(argv[1], "P+NS") && strcmp(argv[1], "NS")) ||
	    (n = atoi(argv[2])) < 1) {
		fprintf(stderr, "usage: %s <P|P+NS|NS> <N> [program]\n", argv[0]);
		return 2;
	}
	int ns_only = !strcmp(argv[1], "NS"), new_ns = !strcmp(argv[1], "P+NS");
	const char *prog = argc > 3 ? argv[3] : "./small";
	pids = calloc(n, sizeof *pids);

	/* Each namespace is held open by one descriptor, so allow N plus some spare. */
	struct rlimit rl = { n + 64, n + 64 };
	if (setrlimit(RLIMIT_NOFILE, &rl) < 0)
		fail("setrlimit");

	/* Block SIGTERM/SIGINT; they are picked up with sigwait() after READY. */
	sigset_t sigs;
	sigemptyset(&sigs);
	sigaddset(&sigs, SIGTERM);
	sigaddset(&sigs, SIGINT);
	sigprocmask(SIG_BLOCK, &sigs, NULL);

	if (ns_only) {
		for (created = 0; created < n; created++) {
			if (unshare(CLONE_NEWNET) < 0)
				fail("unshare");
			if (open("/proc/self/ns/net", O_RDONLY) < 0) /* keeps the namespace alive */
				fail("open namespace descriptor");
		}
	} else {
		int p[2];
		if (pipe(p) < 0)
			fail("pipe");
		for (created = 0; created < n; created++) {
			pid_t pid = fork();
			if (pid < 0)
				fail("fork");
			if (pid == 0) {
				dup2(p[1], 1); /* the program's stdout is the readiness pipe */
				close(p[0]);
				close(p[1]);
				sigprocmask(SIG_UNBLOCK, &sigs, NULL);
				if (new_ns && unshare(CLONE_NEWNET) < 0) {
					perror("unshare");
					_exit(1);
				}
				execl(prog, prog, (char *)NULL);
				perror(prog);
				_exit(1);
			}
			pids[created] = pid;
		}
		close(p[1]);

		/* Each program writes one line when ready; wait for N lines. */
		int lines = 0;
		char buf[4096];
		while (lines < n) {
			struct pollfd pf = { p[0], POLLIN, 0 };
			if (poll(&pf, 1, 1000) == 0) { /* quiet for 1 s: check nothing went wrong */
				struct timespec zero = { 0, 0 };
				if (waitpid(-1, NULL, WNOHANG) > 0) {
					errno = 0;
					fail("a process exited before it was ready");
				}
				if (sigtimedwait(&sigs, NULL, &zero) > 0) {
					errno = 0;
					fail("interrupted before READY");
				}
				continue;
			}
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

	printf("READY %d\n", n);
	fflush(stdout);

	int sig;
	sigwait(&sigs, &sig); /* hold everything alive until told to release */

	for (int i = 0; i < n; i++)
		if (pids[i] > 0)
			kill(pids[i], SIGTERM);
	for (int i = 0; i < n; i++)
		if (pids[i] > 0)
			waitpid(pids[i], NULL, 0);
	printf("RELEASED\n"); /* NS mode: exiting closes the namespace descriptors */
	return 0;
}
