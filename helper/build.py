"""Builds a Gargoyle release into dist/: the addon zip, the app's installer, and
versions.json (what the app reads to find updates). GitHub runs this from the public source
code for every release (.github/workflows/release.yml), so anyone can see exactly what the
downloads are made from.

    python helper/build.py --tag v1.2.0-addon0.4.0     (everything)
    python helper/build.py --addon                     (just the addon zip)

The app is packaged with PyInstaller as a folder with GargoyleApp.exe in it (a single-file
exe is slower to start and more often mistaken for malware by antivirus programs), then
turned into GargoyleSetup.exe by Inno Setup 6 (helper/installer.iss).

A release also needs release/addon-manifest.json and .sig, made and signed with Gargoyle's
release key before the release is tagged (helper/signing.py). The build stops unless that
manifest is exactly the addon it just built and the signature checks out against the key
in helper/version.py, so a release can't go out with an addon the key didn't sign.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "helper"
sys.path.insert(0, str(HELPER))
import signing  # noqa: E402
ADDON = ROOT / "addon" / "Gargoyle"
OUT = ROOT / "dist"
WORK = ROOT / "build"
ADDON_ZIP = "Gargoyle-addon.zip"
SETUP = "GargoyleSetup.exe"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Gargoyle'), StringStruct('FileDescription', 'Gargoyle app'),
    StringStruct('FileVersion', '{version}'), StringStruct('InternalName', 'GargoyleApp'),
    StringStruct('OriginalFilename', 'GargoyleApp.exe'), StringStruct('ProductName', 'Gargoyle'),
    StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"""


def addon_version():
    toc = (ADDON / "Gargoyle.toc").read_text(encoding="utf-8")
    return re.search(r"^##\s*Version:\s*(\S+)", toc, re.M).group(1)


def app_version():
    return re.search(r'APP_VERSION = "([^"]+)"', (HELPER / "version.py").read_text(encoding="utf-8")).group(1)


def release_tag():
    return f"v{app_version()}-addon{addon_version()}"


def entry(path, version):
    data = path.read_bytes()
    return {"version": version, "file": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def addon_files():
    """{"Gargoyle/...": bytes} for every file of the addon, as released (signing.normalized)."""
    files = {}
    for path in sorted(ADDON.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name = f"Gargoyle/{path.relative_to(ADDON).as_posix()}"
            files[name] = signing.normalized(name, path.read_bytes())
    return files


def addon_manifest(tag):
    """The addon's manifest for a release (what gets signed)."""
    return signing.manifest(tag, addon_version(), addon_files())


def check_signed(tag):
    """The release's signed manifest, checked against the addon and the release key."""
    from version import ADDON_SIGNING_KEY
    folder = ROOT / "release"
    try:
        body = (folder / signing.MANIFEST).read_bytes()
        signature = (folder / signing.SIGNATURE).read_bytes()
    except OSError:
        sys.exit("No signed addon manifest in release/: tag releases with tools/publish_public.py --release.")
    if body != addon_manifest(tag):
        sys.exit("release/addon-manifest.json isn't the addon in this code at this tag.")
    try:
        signing.verify(body, signature, ADDON_SIGNING_KEY)
    except signing.SignatureError as exc:
        sys.exit(f"The addon manifest's signature doesn't check out: {exc}.")
    return body, signature


def build_addon(out=OUT):
    """Zips the addon so it unzips as Gargoyle/... (files in a fixed order with fixed dates,
    so the same code gives the same zip)."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / ADDON_ZIP
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in addon_files().items():
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    print(f"{target.name}: {target.stat().st_size // 1024} KB")
    return target


def find_iscc():
    """Inno Setup's compiler (installed for everyone, per user by winget, or named in ISCC)."""
    places = [os.environ.get("ISCC", ""),
              str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"),
              str(Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"),
              str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe")]
    return next((p for p in places if p and Path(p).is_file()), None)


def build_app(out=OUT):
    version = app_version()
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup 6 isn't installed (winget install JRSoftware.InnoSetup), so the installer can't be built.")
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    # The exe's Properties > Details (name, version), as Windows shows them.
    nums = tuple((list(map(int, version.split("."))) + [0, 0, 0, 0])[:4])
    (WORK / "version_info.txt").write_text(VERSION_INFO.format(nums=nums, version=version), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                    "--name", "GargoyleApp", "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"),
                    "--specpath", str(WORK), "--paths", str(HELPER),
                    "--icon", str(HELPER / "assets" / "gargoyle.ico"),
                    "--version-file", str(WORK / "version_info.txt"),
                    "--add-data", f"{HELPER / 'assets'};assets",
                    "--hidden-import", "pystray._win32",
                    str(HELPER / "gargoyle_app.py")], check=True)
    subprocess.run([iscc, "/Q", f"/DAppVersion={version}", f"/DSource={WORK / 'dist' / 'GargoyleApp'}",
                    f"/O{out}", str(HELPER / "installer.iss")], check=True)
    target = out / SETUP
    print(f"{target.name}: {target.stat().st_size // 1024} KB")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="the release's tag (normally made from the app's and addon's versions)")
    parser.add_argument("--addon", action="store_true", help="only zip the addon")
    args = parser.parse_args()
    shutil.rmtree(OUT, ignore_errors=True)
    addon = build_addon()
    if args.addon:
        return
    tag = args.tag or release_tag()
    if tag != release_tag():
        sys.exit(f"The tag {tag} doesn't match the versions in the code ({release_tag()}).")
    body, signature = check_signed(tag)
    (OUT / signing.MANIFEST).write_bytes(body)
    (OUT / signing.SIGNATURE).write_bytes(signature)
    setup = build_app()
    versions = {"tag": tag, "addon": entry(addon, addon_version()), "app": entry(setup, app_version())}
    (OUT / "versions.json").write_text(json.dumps(versions, indent=1), encoding="utf-8")
    print(json.dumps(versions, indent=1))


if __name__ == "__main__":
    main()
