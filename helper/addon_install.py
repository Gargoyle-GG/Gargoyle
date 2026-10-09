"""Installing and updating the Gargoyle addon, and noticing a new Gargoyle app.

Both are released on GitHub, built there from the public source code (helper/build.py).
Each release has a versions.json saying what's in it: the release's tag, and the addons'
and app's versions, file names, sizes and SHA-256. An addon download is checked against
those before anything is unpacked, every file in it has to sit inside that addon's folder,
and the old copy is only swapped out once the new one is fully unpacked next to it.
Nothing but Interface\\AddOns\\Gargoyle, (when it's ticked in the app's Settings)
Interface\\AddOns\\Gargoyle_Tooltips, and (for Gargoyle's helpers, once they've entered a
helper code) Interface\\AddOns\\Gargoyle_Collector is touched. A new app is installed by its own installer
(self_update.py).

An addon folder that's a link (a developer's copy linked from elsewhere) is never updated.
A link to a folder that's gone, or an update cut short, is put right first (repair).
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
TOOLTIPS = "Gargoyle_Tooltips"  # (Gargoyle Damage Tooltips, its own addon, installed if wanted)
COLLECTOR = "Gargoyle_Collector"  # (the Data Collector, for Gargoyle's helpers)
ADDONS = {"addon": NAME, "tooltips": TOOLTIPS, "collector": COLLECTOR}  # (its key in versions.json: its folder)
OPTIONAL = {TOOLTIPS, COLLECTOR}  # (the ones the app can take out again)
MAX_DOWNLOAD = 10 * 1024 * 1024
MAX_UNPACKED = 20 * 1024 * 1024
MAX_FILES = 500
MAX_VERSIONS = 64 * 1024  # (versions.json)
# Releases' files come from GitHub only (github.com sends downloads on to its file servers;
# the app installer's signed manifest is read from the public repo's own files).
RELEASE_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                 "raw.githubusercontent.com"}
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


def installed_version(game_folder, name=NAME):
    """The "## Version:" of an installed addon, or None if it isn't installed."""
    toc = addons(game_folder) / name / f"{name}.toc"
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


def is_dead_link(folder):
    """A link to a folder that's gone (moved or deleted): neither the game nor the app can
    read it, and it's in the way of installing."""
    return is_linked(folder) and not os.path.exists(folder)


def repair(game_folder, name=NAME, links=True):
    """Puts right what stops an addon from showing or installing, and says what it did (or
    None): a link to a folder that's gone (with `links`: only the link goes, nothing it ever
    pointed to), and an update cut short between moving the old copy aside and putting the
    new one in (the old copy goes back)."""
    target = addons(game_folder) / name
    old = target.with_name(name + ".old")
    done = []
    if links and is_dead_link(target):
        try:
            os.rmdir(target)  # (a junction or folder link: removes the link itself)
        except OSError:
            os.unlink(target)
        done.append("removed a link to a folder that's gone")
    if not os.path.lexists(target) and old.is_dir() and not is_linked(old) and (old / f"{name}.toc").is_file():
        os.replace(old, target)
        done.append("put back the copy an update cut short had moved aside")
    return " and ".join(done) or None


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


def offer(versions, key="addon"):
    """An addon in the latest release ({version, file, size, sha256, url, key, name}), checked,
    or None. `key`: "addon" (Gargoyle), "tooltips" (Gargoyle_Tooltips) or "collector"
    (Gargoyle_Collector)."""
    addon = _file(versions, key, (".zip",)) if key in ADDONS else None
    return {**addon, "key": key, "name": ADDONS[key]} if addon and addon["size"] <= MAX_DOWNLOAD else None


def app_installer(versions):
    """The app's installer in the latest release ({version, file, size, sha256, tag, url}),
    checked, or None."""
    return _file(versions, "app", (".exe",))


def app_update(versions, current):
    """The newer app version in the latest release, or None."""
    app = app_installer(versions)
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


def _members(archive, name):
    """The zip's files, each checked to unpack inside the addon's folder."""
    infos, total = [], 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        parts = path.parts
        if (not parts or parts[0] != name or info.filename.startswith(("/", "\\")) or ":" in info.filename
                or any(not SAFE_NAME.match(p) or DEVICE.match(p) for p in parts)):
            raise InstallError(f"the download has an unexpected file ({info.filename[:60]})")
        total += info.file_size
        infos.append((info, parts[1:]))
    if len(infos) > MAX_FILES or total > MAX_UNPACKED:
        raise InstallError("the download is bigger than expected")
    if not any(parts == (f"{name}.toc",) for _, parts in infos):
        raise InstallError(f"the download isn't the {name} addon")
    return infos


def unpacked(folder, name=NAME):
    """{"Gargoyle/...": sha256} for every file in an unpacked copy of an addon."""
    return {"/".join((name,) + path.relative_to(folder).parts): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


def install(game_folder, data, signed, name=NAME):
    """Unpacks an addon zip into Interface\\AddOns\\<name>, replacing the copy there, but
    only if what's unpacked is exactly the files in the signed manifest (signing.verify):
    nothing missing, nothing extra, nothing changed. Returns the version installed."""
    if name not in ADDONS.values():
        raise InstallError(f"{name[:40]} isn't a Gargoyle addon")
    target = addons(game_folder) / name
    try:
        repair(game_folder, name)
    except OSError as exc:
        raise InstallError(f"the {name} folder couldn't be put right ({exc.__class__.__name__}); "
                           f"deleting Interface\\AddOns\\{name} by hand lets it install again") from None
    if is_linked(target):
        raise InstallError(f"the {name} addon folder is a link to a copy elsewhere, so it's left alone")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InstallError("the download isn't a zip file") from None
    new, old = target.with_name(name + ".new"), target.with_name(name + ".old")
    for leftover in (new, old):  # (from an update that was cut short)
        if os.path.lexists(leftover):
            if is_linked(leftover):
                raise InstallError(f"{leftover.name} in Interface\\AddOns is a link; move it away to update")
            shutil.rmtree(leftover, ignore_errors=True)
            if leftover.exists():
                raise InstallError(f"{leftover.name}, left in Interface\\AddOns by an earlier update, couldn't be "
                                   "removed (a file in it is in use); close the game, or delete it by hand")
    with archive:
        members = _members(archive, name)
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
        same = isinstance(signed, dict) and unpacked(new, name) == signed.get("files")
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
        try:
            if old.exists() and not os.path.lexists(target):
                os.replace(old, target)
        except OSError:
            pass  # (repair() puts it back next time)
        shutil.rmtree(new, ignore_errors=True)
        raise InstallError(f"a file is in use, so it couldn't be replaced ({exc.__class__.__name__}); "
                           "trying again later") from None
    shutil.rmtree(old, ignore_errors=True)
    return installed_version(game_folder, name)


def uninstall(game_folder, name):
    """Takes an optional addon (Damage tooltips, the Data Collector) out of the game again, when
    it's unticked in the app. Only that addon's own folder, and never a linked one. True if it
    was there."""
    if name not in OPTIONAL:
        raise InstallError(f"{name[:40]} isn't an optional addon")
    target = addons(game_folder) / name
    if is_linked(target):
        raise InstallError(f"the {name} addon folder is a link to a copy elsewhere, so it's left alone")
    if not target.is_dir():
        return False
    old = target.with_name(name + ".old")
    if old.exists() and not is_linked(old):
        shutil.rmtree(old, ignore_errors=True)
    try:
        os.replace(target, old)  # (so a file in use leaves the addon whole, not half gone)
    except OSError as exc:
        raise InstallError(f"a file is in use, so it couldn't be removed ({exc.__class__.__name__}); "
                           "trying again later") from None
    shutil.rmtree(old, ignore_errors=True)
    return True


CHOICES = "choices.ini"  # (in the app's folder, written by the installer: helper/installer.iss)


def installer_choice(app_folder):
    """The installer's "Also install Damage tooltips" tick (True or False), or None if the
    installer didn't leave one. Taken once: the file goes after it's read, so a later change
    in the app's Settings sticks (until the next install asks again)."""
    path = Path(app_folder) / CHOICES
    try:
        raw = path.read_bytes()[:8192]
        text = raw.decode("utf-16" if raw.startswith(b"\xff\xfe") else "utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*tooltips\s*=\s*([01])\s*$", text, re.M)
    try:
        path.unlink()
    except OSError:
        pass
    return None if match is None else match.group(1) == "1"
