"""Recovery reads with Windows share-delete and bounded replacement retries."""
import os
import time
from pathlib import Path


def replace_recovery(source, target):
    for attempt in range(40):
        try:
            os.replace(source,target)
            return
        except PermissionError:
            if os.name!='nt' or attempt==39: raise
            # Windows readers/AV may briefly retain a handle even with sharing.
            time.sleep(.025)


def open_shared_read(path):
    if os.name != 'nt':
        return Path(path).open('r',encoding='utf-8')
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                     wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    close=kernel.CloseHandle
    close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    # FILE_SHARE_DELETE lets os.replace/unlink proceed while this reader finishes
    # reading the old version, matching POSIX rename semantics.
    handle=create(str(Path(path).resolve()),0x80000000,0x1|0x2|0x4,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    except BaseException:
        close(handle);raise
    return os.fdopen(descriptor,'r',encoding='utf-8')
