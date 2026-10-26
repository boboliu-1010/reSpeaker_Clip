#ifndef CLIP_UPLOAD_CLEANUP_H
#define CLIP_UPLOAD_CLEANUP_H
#include <stdint.h>
/* Caller holds the upload storage claim; no recording/phone transfer may mutate
 * the tree. 1 = removed, 0 = incomplete, negative = cleanup error. Upload success
 * and cleanup errors are separate. Never call for an unconfirmed upload. */
int upload_cleanup_session(const char *session, const uint8_t destination[32], int (*check)(void));
/* Only resumes explicitly staged, CRC-protected cleanup intents. */
int upload_cleanup_resume(int (*check)(void));
int upload_cleanup_pending(const char *session);
#endif
