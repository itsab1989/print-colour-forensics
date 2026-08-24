#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    for (int k = 0; k < argc; k++) fprintf(stderr, "DEBUG: shim argv[%d]=%s\n", k, argv[k]);
    /* find the first argument that is an existing absolute path AFTER argv[1] */
    int i;
    for (i = 2; i < argc - 1; i++)
        if (argv[i][0] == '/' && access(argv[i], X_OK) == 0) break;
    if (i >= argc - 1) { fprintf(stderr, "cups-exec(shim): no program found\n"); return 1; }
    fprintf(stderr, "DEBUG: shim exec %s (argv0=%s)\n", argv[i], argv[i+1]);
    execv(argv[i], argv + i + 1);
    fprintf(stderr, "cups-exec(shim): execv %s failed\n", argv[i]);
    return 1;
}
