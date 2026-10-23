#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <engine2/igameeventsystem.h>

IGameEventSystem *gameeventsystem();

int main()
{
	gameeventsystem()->RegisterGameEvent( nullptr );

	return 0;
}
