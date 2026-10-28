/* Boa binding protocol. Caller owns idle admission and the configuration mutex. */
#ifndef CLIP_USER_BINDING_H
#define CLIP_USER_BINDING_H
#include <stdbool.h>
#include <stddef.h>
#include "at_server.h"
#include "upload_config.h"
int user_binding_command(struct at_cmd_ctx *ctx, struct upload_config *config,
                         bool *saved, char *response, size_t length);
#endif
