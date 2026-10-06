"""Finding the game folder that has the Gargoyle addon installed (or, before it's
installed, the game's folders to install it into).

WoW keeps each version of the game in its own folder (_retail_, _classic_, ...) under
the install folder. The one to sync is whichever has Interface\\AddOns\\Gargoyle. Only
folder names are looked at here (and, on Windows, the install path the Blizzard installer
records in the registry); nothing of the game's own is read.
"""
import os
import re
import string
from pathlib import Path

VERSION_FOLDER = re.compile(r"^_\w+_$")
COMMON = ["Program Files (x86)/World of Warcraft", "Program Files/World of Warcraft", "World of Warcraft",
          "Games/World of Warcraft", "Warcraft/World of Warcraft", "Blizzard/World of Warcraft",
          "Battle.net/World of Warcraft"]


def _registry_installs():
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for key in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                r"SOFTWARE\Blizzard Entertainment\World of Warcraft"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                path = Path(winreg.QueryValueEx(handle, "InstallPath")[0])
        except OSError:
            continue
        # It names a version folder (…\World of Warcraft\_retail_\); the install is above it.
        found.append(path.parent if VERSION_FOLDER.match(path.name) else path)
    return found


def _drives():
    """The PC's hard drives (Windows), else just "/"."""
    if os.name != "nt":
        return ["/"]
    import ctypes
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    fixed = 3  # DRIVE_FIXED: not card readers, DVD drives or network shares, which can hang or ask for a disk
    return [f"{d}:/" for i, d in enumerate(string.ascii_uppercase)
            if mask >> i & 1 and kernel.GetDriveTypeW(f"{d}:\\") == fixed]


def _candidates():
    roots = _registry_installs()
    drives = _drives()
    for drive in drives:
        roots += [Path(drive) / c for c in COMMON]
    roots.append(Path.home() / "Applications" / "World of Warcraft")  # (macOS)
    return roots


def has_addon(folder):
    return (Path(folder) / "Interface" / "AddOns" / "Gargoyle" / "Gargoyle.toc").is_file()


def version_folders(install):
    """The version folders under an install folder (or the folder itself if it is one)."""
    install = Path(install)
    if VERSION_FOLDER.match(install.name) and install.is_dir():
        return [install]
    return sorted(p for p in install.iterdir() if p.is_dir() and VERSION_FOLDER.match(p.name)) if install.is_dir() else []


def game_folders(install):
    """The version folders under an install folder (or the folder itself if it is one)
    that have the Gargoyle addon."""
    install = Path(install)
    folders = [install] + version_folders(install)
    found = []
    for f in folders:
        if f not in found and has_addon(f):
            found.append(f)
    return found


def find_game_folders(with_addon=True):
    """Every version folder with Gargoyle installed (or every one at all), found in the usual places."""
    seen, found = set(), []
    for root in _candidates():
        try:
            for folder in game_folders(root) if with_addon else version_folders(root):
                key = str(folder.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    found.append(folder)
        except OSError:
            continue
    return found


def interface_version(folder):
    """The "## Interface:" number from the installed Gargoyle.toc."""
    toc = Path(folder) / "Interface" / "AddOns" / "Gargoyle" / "Gargoyle.toc"
    try:
        match = re.search(r"^##\s*Interface:\s*([\d, ]+)", toc.read_text(encoding="utf-8", errors="replace"), re.M)
    except OSError:
        return None
    return match.group(1).strip() if match else None


def saved_files(folder):
    """The Gargoyle addon's saved data, one file per WoW account on this PC."""
    return sorted((Path(folder) / "WTF" / "Account").glob("*/SavedVariables/Gargoyle.lua"))
