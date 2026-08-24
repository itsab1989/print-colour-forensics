#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
int main(int argc, char **argv) {
    if (argc == 1) return 0;                 /* discovery: print nothing */
    const char *tmp = getenv("TMPDIR"); if (!tmp) tmp = "/tmp";
    char path[2048], opts[2048];
    snprintf(path, sizeof path, "%s/cap-%s-%ld.prn", tmp, argv[1], (long)time(NULL));
    snprintf(opts, sizeof opts, "%s/cap-%s-%ld.opts", tmp, argv[1], (long)time(NULL));
    FILE *o = fopen(path, "wb");
    if (!o) { fprintf(stderr, "ERROR: cannot open %s\n", path); return 1; }
    FILE *in = stdin;
    if (argc > 6 && argv[6] && argv[6][0]) { in = fopen(argv[6], "rb"); if (!in) { fclose(o); return 1; } }
    char buf[65536]; size_t n, total = 0;
    while ((n = fread(buf, 1, sizeof buf, in)) > 0) { fwrite(buf, 1, n, o); total += n; }
    fclose(o); if (in != stdin) fclose(in);
    FILE *f = fopen(opts, "w");
    if (f) { fprintf(f, "%s\n", argc > 5 && argv[5] ? argv[5] : ""); fclose(f); }
    fprintf(stderr, "INFO: captured %zu bytes to %s\n", total, path);
    return 0;
}
