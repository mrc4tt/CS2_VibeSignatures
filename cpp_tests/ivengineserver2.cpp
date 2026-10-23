#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <engine2/ivengineserver2.h>

IVEngineServer2 *engineserver();

int main()
{
	engineserver()->GetSteamUniverse();

	return 0;
}
