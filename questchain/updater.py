"""Run Windows updates after the tool's Python and console launcher exit."""

import os
from pathlib import Path
import subprocess
import sys


def handoff_windows_update(command: list[str]) -> None:
    # The helper must use the base Python, outside the uv tool environment that
    # is about to be replaced. Inherit the console so update progress stays visible.
    subprocess.Popen(
        [sys._base_executable, str(Path(__file__).resolve()),
         str(os.getpid()), str(os.getppid()), sys.executable, *command],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _wait_for_app_exit(process_id: int, parent_id: int, tool_python: str) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    handles = []
    try:
        for pid in (process_id, parent_id):
            handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)  # synchronize + query
            if not handle:
                error = ctypes.get_last_error()
                if error == 87:  # The process has already exited.
                    continue
                raise ctypes.WinError(error)
            handles.append(handle)
            if pid == parent_id:
                if kernel.WaitForSingleObject(handle, 0) == 0:
                    continue
                path = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(path))
                if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                    error = ctypes.get_last_error()
                    # The launcher can exit between opening its handle and
                    # querying its image. A signalled handle is already safe.
                    if kernel.WaitForSingleObject(handle, 0) == 0:
                        continue
                    raise ctypes.WinError(error)
                # Console launchers and the venv's Python redirector can hold
                # installed files open. Never wait for the user's shell.
                if (Path(path.value).name.lower() != "questchain.exe"
                        and os.path.normcase(path.value) != os.path.normcase(tool_python)):
                    kernel.CloseHandle(handles.pop())
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


def main() -> int:
    try:
        _wait_for_app_exit(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
        result = subprocess.run(sys.argv[4:])
    except OSError as exc:
        print(f"Could not run the updater: {exc}", file=sys.stderr)
        return 1
    if result.returncode == 0:
        print("QuestChain updated. Start it again with: questchain start", flush=True)
    else:
        print(f"QuestChain update failed (exit code {result.returncode}).", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
