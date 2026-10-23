#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <schemasystem/ischemasystem.h>

ISchemaSystem *schemasystem();

int main()
{
	schemasystem()->GlobalTypeScope();

	return 0;
}
