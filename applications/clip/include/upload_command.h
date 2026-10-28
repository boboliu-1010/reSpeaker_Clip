/* AT operations and background uploads share a bounded admission gate. */
#ifndef CLIP_UPLOAD_COMMAND_H
#define CLIP_UPLOAD_COMMAND_H
#include <stdbool.h>
#include <stdint.h>
int upload_command_begin(const char *name, uint8_t type, bool idle,
                         bool uploading, bool pending, bool transferring);
#ifdef CONFIG_BOA_USER_BINDING
bool upload_command_binding_active(void);
/* Called only after earlier device events have drained. */
bool upload_command_binding_activate(void);
#endif
void upload_command_end(void);
/* Keep the reservation across a successful delayed erase/reboot. */
void upload_command_defer(void);
bool upload_command_claim_upload(void);
void upload_command_release_upload(void);
bool upload_command_claim_ota(void);
void upload_command_release_ota(void);
#endif
