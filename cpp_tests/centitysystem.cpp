#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <entity2/entitysystem.h>

CEntitySystem * entitysystem();

int main() {

    entitysystem()->ClearEntityDatabase(CED_NORMAL);

    return 0;
}
