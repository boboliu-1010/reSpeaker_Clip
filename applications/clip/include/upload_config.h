/* One versioned settings value; credentials never live on removable SD. */
#ifndef CLIP_UPLOAD_CONFIG_H
#define CLIP_UPLOAD_CONFIG_H
#include <stdint.h>
struct upload_config {
    uint32_t version, enabled;
    char ssid[33], password[64], host[96], port[6], device[33], token[97];
    char clock_host[96], clock_port[6];
    uint8_t reserved;
#ifdef CONFIG_BOA_USER_BINDING
    char binding_id[33];
    uint32_t epoch, revision;
#endif
    uint32_t crc;
};
int upload_config_init(struct upload_config *out);
int upload_config_save(struct upload_config *value);
/* Persist first; leave the caller's live configuration unchanged on failure. */
int upload_config_save_network(struct upload_config *value, const char *network, const char *pass);
int upload_config_save_enabled(struct upload_config *value, uint32_t enabled);
int upload_config_save_receiver(struct upload_config *value, const char *server,
                                const char *service, const char *identity, const char *credential);
#ifdef CONFIG_BOA_USER_BINDING
int upload_config_bind(struct upload_config *value, const char *server, const char *service,
                       const char *identity, const char *credential, const char *binding,
                       uint32_t epoch, uint32_t revision);
int upload_config_unbind(struct upload_config *value, const char *binding, uint32_t revision);
#endif
enum upload_config_scope { UPLOAD_FORGET_WIFI, UPLOAD_FORGET_RECEIVER };
int upload_config_forget(struct upload_config *value, enum upload_config_scope scope);
int upload_config_clear(void);
int upload_config_valid(const struct upload_config *value);
#endif
