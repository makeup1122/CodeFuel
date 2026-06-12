"""Single-instance guard via a named Win32 mutex.

If the mutex already exists, another instance is running.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("codefuel.single_instance")

MUTEX_NAME = "Global\\CodeFuel_SingleInstance_Mutex"
ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle = None
        self._already = False
        try:
            import ctypes

            self._handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
            last_error = ctypes.windll.kernel32.GetLastError()
            self._already = last_error == ERROR_ALREADY_EXISTS
        except Exception:
            # Non-Windows or no ctypes -> behave as if single instance.
            logger.debug("mutex unavailable", exc_info=True)
            self._handle = None
            self._already = False

    def already_running(self) -> bool:
        return self._already

    def release(self) -> None:
        if self._handle:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
