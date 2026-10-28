#include "user_binding.h"
#include <zephyr/drivers/hwinfo.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static int binding_uid(char uid[65])
{
    uint8_t id[32];
    ssize_t count = hwinfo_get_device_id(id, sizeof(id));
    if (count <= 0 || count > (ssize_t)sizeof(id)) { return count < 0 ? (int)count : -EIO; }
    for (ssize_t i = 0; i < count; i++) { snprintf(uid + 2*i, 3, "%02x", id[i]); }
    uid[2*count] = 0;
    return 0;
}

static int binding_fields(char *args, char **fields, size_t count)
{
    for (size_t i = 0; i < count; i++) {
        if (!args || !*args) { return -EINVAL; }
        fields[i] = args;
        char *comma = strchr(args, ',');
        if (comma) { *comma++ = 0; }
        args = comma;
    }
    return args ? -EINVAL : 0;
}

static int binding_uint32(const char *text, uint32_t *out)
{
    if (!text || !*text) { return -EINVAL; }
    uint32_t value = 0;
    for (; *text; text++) {
        if (*text < '0' || *text > '9') { return -EINVAL; }
        uint32_t digit = (uint32_t)(*text - '0');
        if (value > (UINT32_MAX - digit) / 10) { return -EINVAL; }
        value = value * 10 + digit;
    }
    if (!value) { return -EINVAL; }
    *out = value;
    return 0;
}

int user_binding_command(struct at_cmd_ctx *ctx, struct upload_config *config,
                         bool *saved, char *response, size_t length)
{
    char uid[65] = {0}, args[256] = {0}, cleared[33] = {0};
    int ret = binding_uid(uid);
    if (ret) { goto reply; }
    bool query = ctx->type == AT_CMD_TYPE_READ || ctx->type == AT_CMD_TYPE_TEST;
    if (!strcmp(ctx->name, "IDENTITY") && query) {
        ret = snprintf(response, length,
            "{\"ok\":true,\"error\":0,\"data\":{\"device_uid\":\"%s\",\"binding_protocol_version\":1,\"model\":\"reSpeaker Clip\"}}\n", uid);
        return ret < 0 || (size_t)ret >= length ? -ENOSPC : ret;
    }
    if (!strcmp(ctx->name, "BINDING") && query) { goto status; }
    if (ctx->type != AT_CMD_TYPE_SET || !ctx->args ||
        strlen(ctx->args) + strlen(ctx->name) + 4 > 255) { ret = -EINVAL; goto reply; }
    strcpy(args, ctx->args);
    if (!strcmp(ctx->name, "BINDCFG")) {
        char *fields[7];
        uint32_t epoch, revision;
        ret = binding_fields(args, fields, 7);
        if (!ret) { ret = binding_uint32(fields[5], &epoch); }
        if (!ret) { ret = binding_uint32(fields[6], &revision); }
        if (!ret) {
            ret = upload_config_bind(config, fields[0], fields[1], fields[2], fields[3], fields[4], epoch, revision);
        }
    } else if (!strcmp(ctx->name, "BINDCLR")) {
        char *fields[2];
        uint32_t revision;
        ret = binding_fields(args, fields, 2);
        if (!ret) { ret = binding_uint32(fields[1], &revision); }
        if (!ret) { ret = upload_config_unbind(config, fields[0], revision); }
        if (!ret) { strcpy(cleared, fields[0]); }
    } else { ret = -ENOTSUP; }
    if (ret) { goto reply; }
    *saved = true;
status:
    memset(args, 0, sizeof(args));
    ret = snprintf(response, length,
        "{\"ok\":true,\"error\":0,\"data\":{\"device_uid\":\"%s\",\"bound\":%s,\"saved\":%s,\"binding_id\":\"%s\",\"epoch\":%u,\"revision\":%u%s%s%s}}\n",
        uid, config->binding_id[0] ? "true" : "false", *saved ? "true" : "false",
        config->binding_id, (unsigned int)config->epoch, (unsigned int)config->revision,
        cleared[0] ? ",\"cleared_binding_id\":\"" : "", cleared, cleared[0] ? "\"" : "");
    return ret < 0 || (size_t)ret >= length ? -ENOSPC : ret;
reply:
    memset(args, 0, sizeof(args));
    ret = snprintf(response, length, "{\"ok\":false,\"error\":%d}\n", ret);
    return ret < 0 || (size_t)ret >= length ? -ENOSPC : ret;
}
