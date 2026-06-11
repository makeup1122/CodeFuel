"""Isolated repro: does _HoverableIcon receive synthetic WM_MOUSEMOVE notify?

Creates a temporary tray icon, posts WM_NOTIFY(lParam=WM_MOUSEMOVE) to its own
_hwnd, and reports whether the hover callback fired.
"""
import ctypes
import sys
import time

sys.path.insert(0, r"E:\DashBoard")

import pystray
from PIL import Image

from usagetray.ui.tray import _HoverableIcon

WM_NOTIFY = 0x0400 + 11  # pystray's uCallbackMessage (WM_USER + 11)
WM_MOUSEMOVE = 0x0200

hits = []

icon = _HoverableIcon(
    "HoverRepro",
    icon=Image.new("RGBA", (16, 16), (255, 0, 0, 255)),
    menu=pystray.Menu(pystray.MenuItem("noop", lambda i, it: None)),
    on_hover=lambda: hits.append(time.monotonic()),
)
icon.run_detached()
time.sleep(3)

hwnd = icon._hwnd
print("icon _hwnd:", hwnd, " menu_hwnd:", icon._menu_hwnd, flush=True)

if "--wait" in sys.argv:
    # external process will post messages; report hits at the end
    time.sleep(15)
else:
    for _ in range(3):
        ctypes.windll.user32.PostMessageW(hwnd, WM_NOTIFY, 0, WM_MOUSEMOVE)
        time.sleep(0.2)
    time.sleep(1)
print("hover hits:", len(hits), flush=True)
icon.stop()
sys.exit(0 if hits else 1)
