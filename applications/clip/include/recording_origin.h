/* Immutable recording ownership provenance; contains no credential. */
#ifndef CLIP_RECORDING_ORIGIN_H
#define CLIP_RECORDING_ORIGIN_H
#include <stdbool.h>
#include <stdint.h>
/* Called only at new session creation, before session.json/audio are written. */
int recording_origin_create(const char *session, const char *binding, uint32_t epoch);
/* Missing, unknown, torn and mismatched origins deny all uploads. */
bool recording_origin_matches(const char *session, const char *binding, uint32_t epoch);
#endif
