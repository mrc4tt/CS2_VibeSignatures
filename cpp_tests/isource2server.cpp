#include <tier0/platform.h>
#undef RESTRICT
#define RESTRICT

// Avoid pulling edict.h's heavier transitive include chain; eiface.h only needs
// these as pointer/reference types for the ISource2Server layout tests.
#define EDICT_H
#define ISERVERENTITY_H
class CGlobalVars;
class CCheckTransmitInfo;
class CSharedEdictChangeInfo;
class IServerEntity;
struct edict_t;
struct ChangeAccessorFieldPathIndex_t
{
	int32 m_Value;
};

#include <entity2/entityidentity.h>
#include <eiface.h>

ISource2Server *sourceserver();

int main()
{
	sourceserver()->PreWorldUpdate(false);

	return 0;
}
