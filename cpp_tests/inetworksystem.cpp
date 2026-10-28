#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <networksystem/inetworksystem.h>

INetworkSystem * networksystem();

int main() {

    networksystem()->InitGameServer();

    return 0;
}
