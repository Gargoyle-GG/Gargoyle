"""Starting the Gargoyle app with Windows (off unless you turn it on in the app).

It's the usual per-user way: a "Gargoyle" entry in HKEY_CURRENT_USER's Run list, which
Windows' Task Manager also shows under Startup. No admin rights, nothing system-wide.
Started that way, the app opens quietly in the tray (--tray).
"""
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ENTRY = "Gargoyle"

try:
    import winreg
except ImportError:  # (not Windows)
    winreg = None


def command():
    """What Windows runs at sign-in: the app, in the tray."""
    if getattr(sys, "frozen", False):  # (the packaged GargoyleApp.exe)
        return f'"{sys.executable}" --tray'
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")  # (no console window from source)
    script = Path(__file__).resolve().with_name("gargoyle_app.py")
    return f'"{windowless if windowless.is_file() else python}" "{script}" --tray'


def available():
    return winreg is not None


def enabled():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, ENTRY)
        return True
    except OSError:
        return False


def set_enabled(on):
    if winreg is None:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, ENTRY, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, ENTRY)
            except FileNotFoundError:
                pass


def refresh():
    """If it's on, point it at this copy of the app (in case the app was moved or updated)."""
    if enabled():
        set_enabled(True)
