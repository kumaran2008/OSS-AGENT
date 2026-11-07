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

/* Fast bounding-box pixel diff for ORYN Stage-5 Local Vision (<0.5ms)
 * Compares prev_frame and curr_frame (width * height * channels bytes).
 * Writes [min_x, min_y, max_x, max_y, changed_pixels] to out_rect[5].
 */
int32_t jev_compute_dirty_rect(
    const uint8_t *prev_frame,
    const uint8_t *curr_frame,
    int32_t width,
    int32_t height,
    int32_t channels,
    int32_t threshold,
    int32_t *out_rect
) {
    if (!prev_frame || !curr_frame || width <= 0 || height <= 0 || channels <= 0) {
        return 0;
    }
    int32_t min_x = width;
    int32_t min_y = height;
    int32_t max_x = -1;
    int32_t max_y = -1;
    int32_t changed_count = 0;
    size_t row_stride = (size_t)width * (size_t)channels;

    for (int32_t y = 0; y < height; ++y) {
        size_t row_offset = (size_t)y * row_stride;
        for (int32_t x = 0; x < width; ++x) {
            size_t idx = row_offset + ((size_t)x * (size_t)channels);
            int diff = 0;
            for (int32_t c = 0; c < channels; ++c) {
                int delta = (int)curr_frame[idx + c] - (int)prev_frame[idx + c];
                if (delta < 0) delta = -delta;
                if (delta > threshold) {
                    diff = 1;
                    break;
                }
            }
            if (diff) {
                changed_count++;
                if (x < min_x) min_x = x;
                if (y < min_y) min_y = y;
                if (x > max_x) max_x = x;
                if (y > max_y) max_y = y;
            }
        }
    }

    if (changed_count == 0 || max_x < min_x || max_y < min_y) {
        out_rect[0] = 0;
        out_rect[1] = 0;
        out_rect[2] = 0;
        out_rect[3] = 0;
        out_rect[4] = 0;
        return 0;
    }
    out_rect[0] = min_x;
    out_rect[1] = min_y;
    out_rect[2] = max_x + 1;
    out_rect[3] = max_y + 1;
    out_rect[4] = changed_count;
    return changed_count;
}
