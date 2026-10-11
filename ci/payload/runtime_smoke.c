/* SPDX-License-Identifier: GPL-3.0-only */
/* Own console payload: no CRT, network, graphics or third-party executable. */
#include <windows.h>

#ifndef LUNARBRIDGE_BITS
#error LUNARBRIDGE_BITS must be selected by the build recipe
#endif

_Static_assert(sizeof(void *) * 8 == LUNARBRIDGE_BITS, "wrong target architecture");

#if LUNARBRIDGE_BITS == 64
static const char result[] = "LUNARBRIDGE_WIN64_RUNTIME_OK\n";
static const WCHAR result_path[] = L"lunarbridge-win64.result";
#elif LUNARBRIDGE_BITS == 32
static const char result[] = "LUNARBRIDGE_WIN32_RUNTIME_OK\n";
static const WCHAR result_path[] = L"lunarbridge-win32.result";
#else
#error Only x64 and x86 payloads are supported
#endif

static BOOL write_result(HANDLE destination)
{
    DWORD written = 0;
    const DWORD length = (DWORD)(sizeof(result) - 1);
    return WriteFile(destination, result, length, &written, NULL) && written == length;
}

void smoke_entry(void)
{
    HANDLE output;
    HANDLE marker = CreateFileW(result_path, GENERIC_WRITE, 0, NULL, CREATE_NEW,
                                FILE_ATTRIBUTE_NORMAL, NULL);
    if (marker == INVALID_HANDLE_VALUE) ExitProcess(101);
    if (!write_result(marker)) {
        CloseHandle(marker);
        ExitProcess(102);
    }
    if (!CloseHandle(marker)) ExitProcess(103);
    output = GetStdHandle(STD_OUTPUT_HANDLE);
    if (output == NULL || output == INVALID_HANDLE_VALUE || !write_result(output))
        ExitProcess(104);
    ExitProcess(0);
}
