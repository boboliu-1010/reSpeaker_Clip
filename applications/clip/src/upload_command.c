#include <zephyr/sys/atomic.h>
#include <errno.h>
#include <string.h>
#include "at_server.h"
#include "upload_command.h"

enum { AVAILABLE, COMMAND, UPLOAD, DEFERRED, OTA };
static atomic_t admission;

static bool one_of(const char *name, const char *const *names, size_t count)
{
    for (size_t i = 0; i < count; i++) {
        if (!strcmp(name, names[i])) { return true; }
    }
    return false;
}
#define IN(names) one_of(name, names, sizeof(names) / sizeof(names[0]))

int upload_command_begin(const char *name, uint8_t type, bool idle,
                         bool uploading, bool pending, bool transferring)
{
    static const char *const settings[] = {
        "MODE", "AUTODEL", "BRIGHTNESS", "NAME", "TIME", "LOG", "USB",
    };
    static const char *const queryable[] = {"PAIR", "WIFI", "WIFICFG"};
    static const char *const storage[] = {"LIST", "MARKS", "STORAGE"};
    static const char *const exclusive[] = {
        "DELETE", "FORMAT", "DOWNLOAD", "CANCEL", "WIFI", "WIFICFG",
        "POWEROFF", "REBOOT", "DFU", "PAIR", "FACTORY",
    };
    /* Match the baseline handlers: these EXEC forms also perform a query.
     * Command flags/argument validation still belong to the AT registry. */
    bool query = type == AT_CMD_TYPE_READ || type == AT_CMD_TYPE_TEST;
    if ((IN(settings) && type != AT_CMD_TYPE_SET) || (IN(queryable) && query) ||
        !strcmp(name, "DEVICE") || !strcmp(name, "GSTAT") ||
        !strcmp(name, "BATT") || !strcmp(name, "VERSION")) { return 0; }

    bool storage_query = IN(storage);
    bool guarded = storage_query || IN(exclusive) || IN(settings);
    bool recording = !strcmp(name, "START") || !strcmp(name, "STOP") ||
                     !strcmp(name, "PAUSE") || !strcmp(name, "RESUME") || !strcmp(name, "MARK");
    if ((atomic_get(&admission) == DEFERRED || atomic_get(&admission) == OTA) &&
        (guarded || recording)) { return -EBUSY; }
    /* START/STOP use the event dispatcher, including upload preemption. */
    if (recording) {
        return (uploading || pending) && strcmp(name, "START") && strcmp(name, "STOP") ? -EBUSY : 0;
    }
    /* Upload controls and optional diagnostics enforce their own typed policy.
     * Unregistered commands must reach the registry's Unknown command response. */
    if (!guarded) { return 0; }
    bool cancel = !strcmp(name, "CANCEL");
    if (uploading || pending || (!storage_query && !cancel && (!idle || transferring))) { return -EBUSY; }
    return atomic_cas(&admission, AVAILABLE, COMMAND) ? 0 : -EBUSY;
}

void upload_command_end(void) { (void)atomic_cas(&admission, COMMAND, AVAILABLE); }
void upload_command_defer(void) { (void)atomic_cas(&admission, COMMAND, DEFERRED); }
bool upload_command_claim_upload(void) { return atomic_cas(&admission, AVAILABLE, UPLOAD); }
void upload_command_release_upload(void) { (void)atomic_cas(&admission, UPLOAD, AVAILABLE); }
bool upload_command_claim_ota(void) { return atomic_cas(&admission, AVAILABLE, OTA); }
void upload_command_release_ota(void) { (void)atomic_cas(&admission, OTA, AVAILABLE); }
