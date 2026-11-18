/* small.c: the Small program. Reports ready, then sleeps until killed. */
#include <unistd.h>

int main(void)
{
	/* stdout is the driver's readiness pipe: one line means "I'm ready". */
	if (write(1, "0\n", 2) != 2) /* readiness line for the driver */
		return 1;
	/* Sleep until a signal (SIGTERM from release()) ends the program. */
	pause();
	return 0;
}
