#include <Python.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char raw[PATH_MAX], executable[PATH_MAX], base[PATH_MAX];
    uint32_t size = sizeof(raw);
    if (_NSGetExecutablePath(raw, &size) || !realpath(raw, executable)) return 1;
    strcpy(base, executable);
    char *slash = strrchr(base, '/');
    if (!slash) return 1;
    *slash = 0;
    char home[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    snprintf(home, sizeof(home), "%s/../Resources/python", base);
    snprintf(python, sizeof(python), "%s/bin/python3.12", home);
    snprintf(script, sizeof(script), "%s/../Resources/studio/studio.py", base);
    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.write_bytecode = 0;
    config.parse_argv = 0;
    PyStatus status = PyConfig_SetBytesString(&config, &config.home, home);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.executable, python);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.run_filename, script);
    char **args = calloc(argc + 1, sizeof(char*));
    args[0] = script;
    for (int i=1; i<argc; i++) args[i] = argv[i];
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesArgv(&config, argc, args);
    free(args);
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    // Isolated Python does not prepend script directories; add only our own code.
    char code[PATH_MAX * 2];
    // Resolve via sys.argv; no user path is interpolated into Python source.
    snprintf(code, sizeof(code), "import sys, pathlib; sys.path.insert(0, str(pathlib.Path(sys.argv[0]).resolve().parent))");
    if (PyRun_SimpleString(code)) return 1;
    return Py_RunMain();
}
