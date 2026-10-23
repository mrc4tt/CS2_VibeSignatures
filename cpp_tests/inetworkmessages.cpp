#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <networksystem/inetworkmessages.h>

INetworkMessages * networkmessages();

int main() {

    networkmessages()->GetLoggingChannel();

    return 0;
}
