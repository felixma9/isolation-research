/* small.c: the Small program. Prints one line, then sleeps until killed. */
#include <unistd.h>

int main(void)
{
	/* One line on stdout says "I'm running" (the run scripts send it to /dev/null). */
	if (write(1, "0\n", 2) != 2)
		return 1;
	/* Sleep until a signal (the run script's kill) ends the program. */
	pause();
	return 0;
}
