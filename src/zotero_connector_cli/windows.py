from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9
WM_CLOSE = 0x0010
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_S = 0x53
VK_W = 0x57


ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    executable: str
    title: str

    @property
    def process_name(self) -> str:
        return Path(self.executable).stem.lower()


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _process_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def list_windows() -> list[Window]:
    windows: list[Window] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd).strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        executable = _process_path(pid.value)
        if executable:
            windows.append(Window(hwnd=int(hwnd), pid=pid.value, executable=executable, title=title))
        return True

    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return windows


def foreground_window() -> Window | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    matches = [window for window in list_windows() if window.hwnd == int(hwnd)]
    return matches[0] if matches else None


def find_browser_window(process_names: set[str], title_contains: str | None = None) -> Window:
    candidates = [
        window
        for window in list_windows()
        if window.process_name in process_names
        and (not title_contains or title_contains.casefold() in window.title.casefold())
    ]
    if not candidates:
        detail = f" with title containing {title_contains!r}" if title_contains else ""
        raise RuntimeError(f"No visible browser window found{detail}")

    foreground = foreground_window()
    if foreground and not foreground.title.casefold().startswith("the extension "):
        for candidate in candidates:
            if candidate.hwnd == foreground.hwnd:
                return candidate

    return max(candidates, key=lambda window: len(window.title))


def activate_window(window: Window) -> None:
    user32.ShowWindow(window.hwnd, SW_RESTORE)
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(window.hwnd, None)
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

    attached_target = False
    attached_foreground = False
    try:
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread not in (current_thread, target_thread):
            attached_foreground = bool(
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            )
        user32.BringWindowToTop(window.hwnd)
        user32.SetForegroundWindow(window.hwnd)
    finally:
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)

    time.sleep(0.25)
    if user32.GetForegroundWindow() != window.hwnd:
        alt = (INPUT * 2)(
            _keyboard_input(VK_MENU),
            _keyboard_input(VK_MENU, key_up=True),
        )
        user32.SendInput(len(alt), alt, ctypes.sizeof(INPUT))
        user32.BringWindowToTop(window.hwnd)
        user32.SetForegroundWindow(window.hwnd)
        time.sleep(0.25)
    if user32.GetForegroundWindow() != window.hwnd:
        raise RuntimeError(
            "Windows refused to foreground the browser; click the target browser and retry"
        )


def close_window(window: Window) -> None:
    if not user32.PostMessageW(window.hwnd, WM_CLOSE, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def _keyboard_input(vk: int, key_up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else 0
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0))


def send_ctrl_w() -> None:
    events = (INPUT * 4)(
        _keyboard_input(VK_CONTROL),
        _keyboard_input(VK_W),
        _keyboard_input(VK_W, key_up=True),
        _keyboard_input(VK_CONTROL, key_up=True),
    )
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


def send_ctrl_shift_s() -> None:
    events = (INPUT * 6)(
        _keyboard_input(VK_CONTROL),
        _keyboard_input(VK_SHIFT),
        _keyboard_input(VK_S),
        _keyboard_input(VK_S, key_up=True),
        _keyboard_input(VK_SHIFT, key_up=True),
        _keyboard_input(VK_CONTROL, key_up=True),
    )
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


def executable_candidates(browser: str) -> list[Path]:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))

    candidates = {
        "edge": [
            program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
            program_files / "Microsoft/Edge/Application/msedge.exe",
        ],
        "brave": [
            program_files / "BraveSoftware/Brave-Browser/Application/brave.exe",
            program_files_x86 / "BraveSoftware/Brave-Browser/Application/brave.exe",
            local_app_data / "BraveSoftware/Brave-Browser/Application/brave.exe",
        ],
        "chrome": [
            program_files / "Google/Chrome/Application/chrome.exe",
            program_files_x86 / "Google/Chrome/Application/chrome.exe",
            local_app_data / "Google/Chrome/Application/chrome.exe",
        ],
        "firefox": [
            program_files / "Mozilla Firefox/firefox.exe",
            program_files_x86 / "Mozilla Firefox/firefox.exe",
        ],
    }
    return candidates[browser]


def find_browser_executable(browser: str) -> Path | None:
    return next((path for path in executable_candidates(browser) if path.is_file()), None)
