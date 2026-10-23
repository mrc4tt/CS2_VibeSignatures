#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

#include <filesystem/ifilesystem.h>

IFileSystem *filesystem();

int main()
{
	filesystem()->Read( nullptr, 0, nullptr );

	return 0;
}
