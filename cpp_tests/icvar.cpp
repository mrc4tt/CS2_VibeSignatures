#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <tier0/icvar.h>

ICvar *cvar();

int main()
{
	cvar()->FindFirstConVar();

	return 0;
}
