#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <igameevents.h>

IGameEventManager2 * gameeventmanager();

int main() {

    gameeventmanager()->Reset();

    return 0;
}
