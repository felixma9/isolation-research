/* netns.h: network namespace helpers. Need root (CAP_SYS_ADMIN). */
#ifndef NETNS_H
#define NETNS_H

/* Move the calling process into a new network namespace. For spawn_n()'s
 * before_exec. Returns -1 after printing an error. */
int netns_enter(void);

/* Create one new, empty network namespace and keep it alive with an open
 * descriptor, until the program exits. Calls fail() on error. */
void netns_hold(void);

#endif
