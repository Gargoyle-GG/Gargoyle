"""Installing and updating the Gargoyle addon, and noticing a new Gargoyle app.

Both are released on GitHub, built there from the public source code (helper/build.py).
Each release has a versions.json saying what's in it: the release's tag, and the addon's
and app's versions, file names, sizes and SHA-256. The addon download is checked against
those before anything is unpacked, every file in it has to sit inside a Gargoyle folder,
and the old copy is only swapped out once the new one is fully unpacked next to it.
Nothing but Interface\\AddOns\\Gargoyle is touched. The app itself isn't replaced: it says
a new version is out, and its download is the installer.

A Gargoyle folder that's a link (a developer's copy linked from elsewhere) is never updated.
"""

import hashlib
import io
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from version import RELEASES

NAME = "Gargoyle"
MAX_DOWNLOAD = 10 * 1024 * 1024
MAX_UNPACKED = 20 * 1024 * 1024
MAX_FILES = 500
MAX_VERSIONS = 64 * 1024  # (versions.json)
# Releases' files come from GitHub only (github.com sends downloads on to its file servers).
RELEASE_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
TAG = re.compile(r"^[A-Za-z0-9._+-]{1,60}$")
FILE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
# Names a file in the addon may have: plain letters and digits, not ending in a dot or space
# (Windows drops those), and not one of Windows' device names (CON, NUL, COM1...).
SAFE_NAME = re.compile(r"^[A-Za-z0-9_()+-][A-Za-z0-9 _.()+-]{0,99}(?<![. ])$")
DEVICE = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.I)


class InstallError(Exception):
    pass


def addons(game_folder):
    return Path(game_folder) / "Interface" / "AddOns"


def installed_version(game_folder):
    """The "## Version:" of the installed addon, or None if it isn't installed."""
    toc = addons(game_folder) / NAME / "Gargoyle.toc"
    try:
        text = toc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^##\s*Version:\s*(\S+)", text, re.M)
    return match.group(1) if match else "?"


def is_linked(folder):
    """Is this folder a link (junction or symbolic link) to somewhere else?"""
    try:
        info = os.lstat(folder)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def parse_version(text):
    """"1.2.10" -> (1, 2, 10); anything odd -> None."""
    if not isinstance(text, str) or not re.match(r"^\d+(\.\d+){0,3}$", text):
        return None
    return tuple(int(p) for p in text.split("."))


def newer(available, current):
    """Is `available` a later version than `current` (None or "?": not installed or unknown)?"""
    a, c = parse_version(available), parse_version(current)
    if a is None:
        return False
    return c is None or a > c


def _file(versions, key, extensions):
    """A release file's entry in versions.json, checked, with its download address added."""
    entry = versions.get(key) if isinstance(versions, dict) else None
    tag = versions.get("tag") if isinstance(versions, dict) else None
    if not isinstance(entry, dict) or not isinstance(tag, str) or not TAG.match(tag):
        return None
    name = entry.get("file")
    ok = (parse_version(entry.get("version")) and isinstance(name, str) and FILE.match(name) and name.endswith(extensions)
          and isinstance(entry.get("sha256"), str) and re.match(r"^[0-9a-f]{64}$", entry["sha256"])
          and isinstance(entry.get("size"), int) and not isinstance(entry["size"], bool) and 0 < entry["size"])
    return {**entry, "tag": tag, "url": f"{RELEASES}/download/{tag}/{name}"} if ok else None


def offer(versions):
    """The addon in the latest release ({version, file, size, sha256, url}), checked, or None."""
    addon = _file(versions, "addon", (".zip",))
    return addon if addon and addon["size"] <= MAX_DOWNLOAD else None


def app_update(versions, current):
    """The newer app version in the latest release, or None."""
    app = _file(versions, "app", (".exe",))
    return app["version"] if app and newer(app["version"], current) else None


def app_download(versions):
    """The new app's installer, or None (then the releases page)."""
    app = _file(versions, "app", (".exe",))
    return app["url"] if app else None


def from_github(url):
    """Is this a release address the app may download from?"""
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in RELEASE_HOSTS


def check_download(data, addon):
    if len(data) != addon["size"] or hashlib.sha256(data).hexdigest() != addon["sha256"]:
        raise InstallError("the download didn't arrive whole; trying again later")


def _members(archive):
    """The zip's files, each checked to unpack inside the Gargoyle folder."""
    infos, total = [], 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        parts = path.parts
        if (not parts or parts[0] != NAME or info.filename.startswith(("/", "\\")) or ":" in info.filename
                or any(not SAFE_NAME.match(p) or DEVICE.match(p) for p in parts)):
            raise InstallError(f"the download has an unexpected file ({info.filename[:60]})")
        total += info.file_size
        infos.append((info, parts[1:]))
    if len(infos) > MAX_FILES or total > MAX_UNPACKED:
        raise InstallError("the download is bigger than expected")
    if not any(parts == ("Gargoyle.toc",) for _, parts in infos):
        raise InstallError("the download isn't the Gargoyle addon")
    return infos


def unpacked(folder):
    """{"Gargoyle/...": sha256} for every file in an unpacked copy of the addon."""
    return {"/".join((NAME,) + path.relative_to(folder).parts): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


def install(game_folder, data, signed):
    """Unpacks the addon zip into Interface\\AddOns\\Gargoyle, replacing the copy there, but
    only if what's unpacked is exactly the files in the signed manifest (signing.verify):
    nothing missing, nothing extra, nothing changed. Returns the version installed."""
    target = addons(game_folder) / NAME
    if is_linked(target):
        raise InstallError("the Gargoyle addon folder is a link to a copy elsewhere, so it's left alone")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InstallError("the download isn't a zip file") from None
    new, old = target.with_name(NAME + ".new"), target.with_name(NAME + ".old")
    for leftover in (new, old):  # (from an update that was cut short)
        if leftover.exists() and not is_linked(leftover):
            shutil.rmtree(leftover, ignore_errors=True)
    with archive:
        members = _members(archive)
        new.mkdir(parents=True)
        inside = new.resolve()
        try:
            for info, parts in members:
                if info.is_dir() or not parts:
                    continue
                path = new.joinpath(*parts)
                if not path.resolve().is_relative_to(inside):  # (Windows quirks: "a." is "a", "CON" is a device...)
                    raise InstallError(f"the download has an unexpected file ({info.filename[:60]})")
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except InstallError:
            shutil.rmtree(new, ignore_errors=True)
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            shutil.rmtree(new, ignore_errors=True)
            raise InstallError(f"unpacking it didn't work ({exc.__class__.__name__})") from None
    # What's on disk now has to be exactly what Gargoyle's release key signed.
    try:
        same = isinstance(signed, dict) and unpacked(new) == signed.get("files")
    except OSError:
        same = False
    if not same:
        shutil.rmtree(new, ignore_errors=True)
        raise InstallError("the download doesn't match Gargoyle's signed release, so it wasn't installed")
    # The swap: the old copy steps aside, the new one takes its place, the old one goes.
    try:
        if target.exists():
            os.replace(target, old)
        os.replace(new, target)
    except OSError as exc:
        if old.exists() and not target.exists():
            os.replace(old, target)
        shutil.rmtree(new, ignore_errors=True)
        raise InstallError(f"a file is in use, so it couldn't be replaced ({exc.__class__.__name__}); "
                           "trying again later") from None
    shutil.rmtree(old, ignore_errors=True)
    return installed_version(game_folder)
