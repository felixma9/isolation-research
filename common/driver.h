/* driver.h: shared code for benchmark programs that create N things (processes,
 * namespaces, ...), hold them alive while memory is measured, then release them.
 *
 * Every such program talks to run.py the same way:
 *   prints "READY N" once all N exist,
 *   waits for SIGTERM or Ctrl-C,
 *   releases everything and prints "RELEASED".
 * On any failure it says which step failed, exits non-zero and never prints READY.
 *
 * Typical main():
 *     driver_init(n);
 *     spawn_n("build/small", NULL);   // or create N things another way
 *     hold();
 *     release();
 */
#ifndef DRIVER_H
#define DRIVER_H

extern int n;       /* how many to create */
extern int created; /* how many exist so far (shown in failure messages) */

/* Print "<what> (created of n created): <errno text>", kill any started processes, exit 1. */
void fail(const char *what);

/* Set n, allow enough open files for one descriptor per thing, and block
 * SIGTERM/SIGINT so hold() can wait for them. Call first. */
void driver_init(int count);

/* Start n copies of `program`, and wait until each has written its readiness line.
 * In each child, `before_exec` (if not NULL) runs just before exec; it returns
 * -1 after printing its own error to make that child fail. */
void spawn_n(const char *program, int (*before_exec)(void));

/* Print "READY n" and wait for SIGTERM or Ctrl-C. */
void hold(void);

/* Stop and reap every process spawn_n() started, then print "RELEASED". */
void release(void);

#endif
