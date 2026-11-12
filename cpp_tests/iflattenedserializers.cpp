#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <networksystem/iflattenedserializers.h>

IFlattenedSerializers * flattenedserializers();

int main() {

    flattenedserializers()->FindOrCreateCreateFlattenedSerializers( nullptr, 0 );

    return 0;
}
