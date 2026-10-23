#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <engine2/networkgameserverbase.h>

INetworkGameServer * networkgameserver();
CNetworkGameServerBase * networkgameserverbase();

int main() {

    networkgameserver()->Shutdown();
    networkgameserverbase()->SetMaxClients(64);

    return 0;
}
