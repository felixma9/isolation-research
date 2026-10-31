/* small.c: the Small program. Reports ready, then sleeps until killed. */
#include <unistd.h>

int main(void)
{
	if (write(1, "0\n", 2) != 2) /* readiness line for the driver */
		return 1;
	pause();
	return 0;
}
