"""The app's settings, in %APPDATA%\\Gargoyle\\config.json: the website, the game folder,
the account token, and which in-game signups were already sent (and what the website said).

The token is encrypted with Windows' own per-user protection (DPAPI), so another account
on the PC, or a copy of the file, can't use it. (Off Windows it's stored as it is.)
"""
import base64
import json
import os
import sys
import threading
from pathlib import Path

SITE = "https://gargoyle.gg"


def folder():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "Gargoyle"


# ---- DPAPI (Windows) ----

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _call(fn, data):
        blob_in = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError("Windows couldn't protect or unprotect the token")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def protect(data):
        return _call(ctypes.windll.crypt32.CryptProtectData, data)

    def unprotect(data):
        return _call(ctypes.windll.crypt32.CryptUnprotectData, data)
else:
    def protect(data):
        return data

    def unprotect(data):
        return data


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else folder() / "config.json"
        self.lock = threading.RLock()  # (the window and the syncing thread both save)
        self.data = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(temp, self.path)

    @property
    def site(self):
        return (os.environ.get("GARGOYLE_SITE") or self.data.get("site") or SITE).rstrip("/")

    @property
    def token(self):
        stored = self.data.get("token")
        if not stored:
            return None
        try:
            return unprotect(base64.b64decode(stored)).decode()
        except (OSError, ValueError):
            return None

    @token.setter
    def token(self, value):
        with self.lock:
            if value:
                self.data["token"] = base64.b64encode(protect(value.encode())).decode()
            else:
                self.data.pop("token", None)
                self.data.pop("user", None)
            self.save()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
            self.save()
