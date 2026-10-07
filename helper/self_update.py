"""Updating the Gargoyle app itself ("Update now" in its window).

The latest release's installer (GargoyleSetup.exe) is downloaded from GitHub and run only if
it's exactly the one Gargoyle's release key signed: once GitHub has built a release, its
installer's size and SHA-256 are signed into app-manifest.json in the public repo
(tools/publish_public.py --sign-app; signing.py). Until then the app offers the release's
download page, as it always did.

The installer runs quietly. It closes this app, puts the new version in its place and opens
it again (installer.iss: /fromapp=1 also leaves the app's own settings, like starting with
Windows and Damage tooltips, as they are).
"""
import hashlib
import subprocess
import tempfile
from pathlib import Path

import addon_install

MAX_INSTALLER = 150 * 1024 * 1024
ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/fromapp=1"]
FOLDER = "GargoyleUpdate"  # (in Windows' temp folder)


def installer(versions, current):
    """The newer app's installer in the latest release, or None."""
    app = addon_install.app_installer(versions)
    if app and app["size"] <= MAX_INSTALLER and addon_install.newer(app["version"], current):
        return app
    return None


def matches(signed, app):
    """Is the signed manifest (signing.verify_app) this release's installer?"""
    return all(signed.get(k) == app[k] for k in ("tag", "version", "file", "size", "sha256"))


def save(data, app, temp=None):
    """Checks the downloaded installer against the release (and so its signed manifest) and
    saves it to run. Installers saved before are cleared away. Returns its path."""
    if len(data) != app["size"] or hashlib.sha256(data).hexdigest() != app["sha256"]:
        raise addon_install.InstallError("the download didn't arrive whole, or isn't the signed installer")
    folder = Path(temp or tempfile.gettempdir()) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    clear(temp)
    path = folder / f"GargoyleSetup-{app['version']}.exe"
    path.write_bytes(data)
    return path


def clear(temp=None):
    """Installers left from earlier updates."""
    for old in (Path(temp or tempfile.gettempdir()) / FOLDER).glob("GargoyleSetup-*.exe"):
        try:
            old.unlink()
        except OSError:
            pass


def run(path, launch=None):
    """Starts the installer on its own (it outlives this app, which it closes)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    (launch or subprocess.Popen)([str(path), *ARGS], close_fds=True, creationflags=flags)
