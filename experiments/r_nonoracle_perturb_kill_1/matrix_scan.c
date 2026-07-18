#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <zlib.h>

#define LINE_CAPACITY 512

static int fail(gzFile input, unsigned long long *total, unsigned long long *detected,
                unsigned long long *mt, const char *message) {
    if (input != NULL) {
        gzclose(input);
    }
    free(total);
    free(detected);
    free(mt);
    fprintf(stderr, "%s\n", message);
    return 2;
}

static int parse_ull(const char *text, unsigned long long *value) {
    if (*text == '\0') {
        return 0;
    }
    for (const char *cursor = text; *cursor != '\0'; cursor++) {
        if (*cursor < '0' || *cursor > '9') {
            return 0;
        }
    }
    char *end = NULL;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') {
        return 0;
    }
    *value = parsed;
    return 1;
}

static int parse_triplet(const char *line, unsigned long long *a, unsigned long long *b,
                         unsigned long long *c) {
    char first[64];
    char second[64];
    char third[64];
    char trailing = '\0';
    if (sscanf(line, "%63s %63s %63s %c", first, second, third, &trailing) != 3) {
        return 0;
    }
    return parse_ull(first, a) && parse_ull(second, b) && parse_ull(third, c);
}

int main(int argc, char **argv) {
    if (argc != 9) {
        fprintf(stderr,
                "usage: matrix_scan INPUT.mtx.gz OUTPUT.tsv ROWS COLS NNZ RNA_ROWS MT_FIRST "
                "MT_LAST\n");
        return 2;
    }

    unsigned long long expected_rows = 0;
    unsigned long long expected_cols = 0;
    unsigned long long expected_nnz = 0;
    unsigned long long rna_rows = 0;
    unsigned long long mt_first = 0;
    unsigned long long mt_last = 0;
    if (!parse_ull(argv[3], &expected_rows) || !parse_ull(argv[4], &expected_cols) ||
        !parse_ull(argv[5], &expected_nnz) || !parse_ull(argv[6], &rna_rows) ||
        !parse_ull(argv[7], &mt_first) || !parse_ull(argv[8], &mt_last)) {
        fprintf(stderr, "all boundaries and dimensions must be unsigned integers\n");
        return 2;
    }
    if (expected_rows == 0 || expected_cols == 0 || expected_nnz == 0 || rna_rows == 0 ||
        rna_rows > expected_rows) {
        fprintf(stderr, "invalid matrix or feature boundary\n");
        return 2;
    }
    if (mt_first == 0 || mt_first > mt_last || mt_last > rna_rows) {
        fprintf(stderr, "invalid mt boundary\n");
        return 2;
    }
    if (expected_cols > SIZE_MAX / sizeof(unsigned long long)) {
        fprintf(stderr, "column count exceeds addressable memory\n");
        return 2;
    }

    gzFile input = gzopen(argv[1], "rb");
    if (input == NULL) {
        fprintf(stderr, "cannot open gzip matrix\n");
        return 2;
    }
    unsigned long long *total = calloc((size_t)expected_cols, sizeof(*total));
    unsigned long long *detected = calloc((size_t)expected_cols, sizeof(*detected));
    unsigned long long *mt = calloc((size_t)expected_cols, sizeof(*mt));
    if (total == NULL || detected == NULL || mt == NULL) {
        return fail(input, total, detected, mt, "cannot allocate metric arrays");
    }

    char line[LINE_CAPACITY];
    if (gzgets(input, line, sizeof(line)) == NULL ||
        strcmp(line, "%%MatrixMarket matrix coordinate integer general\n") != 0) {
        return fail(input, total, detected, mt, "invalid MatrixMarket banner");
    }

    do {
        if (gzgets(input, line, sizeof(line)) == NULL) {
            return fail(input, total, detected, mt, "missing MatrixMarket dimensions");
        }
    } while (line[0] == '%');

    unsigned long long rows = 0;
    unsigned long long cols = 0;
    unsigned long long nnz = 0;
    if (!parse_triplet(line, &rows, &cols, &nnz) || rows != expected_rows ||
        cols != expected_cols || nnz != expected_nnz) {
        return fail(input, total, detected, mt, "matrix dimensions or nnz do not match binding");
    }

    unsigned long long previous_row = 0;
    unsigned long long previous_col = 0;
    for (unsigned long long entry = 0; entry < expected_nnz; entry++) {
        if (gzgets(input, line, sizeof(line)) == NULL) {
            return fail(input, total, detected, mt, "matrix nnz ended before declared count");
        }
        unsigned long long row = 0;
        unsigned long long col = 0;
        unsigned long long value = 0;
        if (!parse_triplet(line, &row, &col, &value) || row == 0 || row > expected_rows ||
            col == 0 || col > expected_cols || value == 0) {
            return fail(input, total, detected, mt, "invalid matrix coordinate or value");
        }
        if (entry > 0 && (col < previous_col || (col == previous_col && row <= previous_row))) {
            return fail(input, total, detected, mt, "matrix coordinate order or duplicate violation");
        }
        previous_row = row;
        previous_col = col;
        if (row <= rna_rows) {
            size_t cell = (size_t)(col - 1);
            if (ULLONG_MAX - total[cell] < value) {
                return fail(input, total, detected, mt, "RNA UMI total overflow");
            }
            total[cell] += value;
            detected[cell] += 1;
            if (row >= mt_first && row <= mt_last) {
                if (ULLONG_MAX - mt[cell] < value) {
                    return fail(input, total, detected, mt, "MT UMI total overflow");
                }
                mt[cell] += value;
            }
        }
    }

    while (gzgets(input, line, sizeof(line)) != NULL) {
        for (size_t index = 0; line[index] != '\0'; index++) {
            if (line[index] != ' ' && line[index] != '\t' && line[index] != '\r' &&
                line[index] != '\n') {
                return fail(input, total, detected, mt, "matrix nnz exceeds declared count");
            }
        }
    }
    int zlib_error = Z_OK;
    (void)gzerror(input, &zlib_error);
    if (zlib_error != Z_OK && zlib_error != Z_STREAM_END) {
        return fail(input, total, detected, mt, "gzip stream failed integrity check");
    }
    if (gzclose(input) != Z_OK) {
        free(total);
        free(detected);
        free(mt);
        fprintf(stderr, "gzip stream failed close integrity check\n");
        return 2;
    }

    size_t temporary_length = strlen(argv[2]) + sizeof(".tmp.XXXXXX");
    char *temporary_path = malloc(temporary_length);
    if (temporary_path == NULL ||
        snprintf(temporary_path, temporary_length, "%s.tmp.XXXXXX", argv[2]) < 0) {
        free(total);
        free(detected);
        free(mt);
        free(temporary_path);
        fprintf(stderr, "cannot allocate temporary output path\n");
        return 2;
    }
    int output_fd = mkstemp(temporary_path);
    if (output_fd < 0) {
        free(total);
        free(detected);
        free(mt);
        free(temporary_path);
        fprintf(stderr, "cannot create temporary output\n");
        return 2;
    }
    FILE *output = fdopen(output_fd, "w");
    if (output == NULL) {
        close(output_fd);
        unlink(temporary_path);
        free(total);
        free(detected);
        free(mt);
        free(temporary_path);
        fprintf(stderr, "cannot open temporary output stream\n");
        return 2;
    }
    int write_failed = fprintf(output, "cell_index\ttotal_umi\tdetected_features\tmt_umi\n") < 0;
    for (unsigned long long col = 0; col < expected_cols && !write_failed; col++) {
        if (fprintf(output, "%llu\t%llu\t%llu\t%llu\n", col + 1, total[col], detected[col],
                    mt[col]) < 0) {
            write_failed = 1;
        }
    }
    if (!write_failed && fflush(output) != 0) {
        write_failed = 1;
    }
    if (!write_failed && fsync(fileno(output)) != 0) {
        write_failed = 1;
    }
    if (fclose(output) != 0) {
        write_failed = 1;
    }
    free(total);
    free(detected);
    free(mt);
    if (write_failed) {
        unlink(temporary_path);
        free(temporary_path);
        fprintf(stderr, "failed writing or syncing metrics output\n");
        return 2;
    }
    if (link(temporary_path, argv[2]) != 0) {
        unlink(temporary_path);
        free(temporary_path);
        fprintf(stderr, "cannot publish metrics output without replacement\n");
        return 2;
    }
    if (unlink(temporary_path) != 0) {
        unlink(argv[2]);
        unlink(temporary_path);
        free(temporary_path);
        fprintf(stderr, "failed removing temporary output link\n");
        return 2;
    }
    free(temporary_path);
    return 0;
}
