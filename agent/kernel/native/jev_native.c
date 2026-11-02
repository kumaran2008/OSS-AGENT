#include <stdint.h>
#include <stddef.h>

/* Fast 64-bit FNV-1a hash for workspace file integrity snapshots (<0.1ms) */
uint64_t jev_fnv1a_64(const uint8_t *data, size_t len) {
    uint64_t hash = 14695981039346656037ULL;
    for (size_t i = 0; i < len; ++i) {
        hash ^= (uint64_t)data[i];
        hash *= 1099511628211ULL;
    }
    return hash;
}

/* Fast token & line estimator (~500 MB/s in C) */
int32_t jev_estimate_tokens(const char *text, size_t len) {
    if (len == 0) return 0;
    int32_t words = 0;
    int32_t symbols = 0;
    int in_word = 0;
    for (size_t i = 0; i < len; ++i) {
        char c = text[i];
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_') {
            if (!in_word) {
                words++;
                in_word = 1;
            }
        } else {
            in_word = 0;
            if (c != ' ' && c != '\n' && c != '\t' && c != '\r') {
                symbols++;
            }
        }
    }
    int32_t est = words + (symbols / 2);
    return est > 0 ? est : 1;
}
