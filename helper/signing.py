"""Signed releases: the app only installs addon files, and only runs a new app installer, that
Gargoyle's release key signed.

GitHub builds every release from the public code, but a GitHub account can be broken into.
So each release also carries addon-manifest.json (every addon file with its SHA-256) and
addon-manifest.sig, an Ed25519 signature over that file made with a key that never goes near
GitHub. The app checks the signature against the public key in version.py, then checks every
file it unpacks against the manifest, and installs nothing that doesn't match. Someone who
got into GitHub could post a release, but not one the app would install.

The manifest is made from the code (build.py, with text files' line endings made "\\n" so
any checkout gives the same bytes), so anyone can check a release's manifest against the
public code at its tag.

The app's installer is only built by GitHub, so it's signed after the build: its size and
SHA-256 go into app-manifest.json (tools/publish_public.py --sign-app), kept in the public
repo's release/ folder. The app's "Update now" runs a downloaded installer only if it's the
one signed there (self_update.py).
"""
import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST = "addon-manifest.json"
SIGNATURE = "addon-manifest.sig"
# Each addon's own manifest and signature ("addon": Gargoyle, "tooltips": Gargoyle_Tooltips,
# "collector": Gargoyle_Collector).
MANIFESTS = {"addon": (MANIFEST, SIGNATURE), "tooltips": ("tooltips-manifest.json", "tooltips-manifest.sig"),
             "collector": ("collector-manifest.json", "collector-manifest.sig")}
APP_MANIFEST = ("app-manifest.json", "app-manifest.sig")  # (the app's installer)
TEXT = {".lua", ".toc", ".xml", ".txt", ".md"}


class SignatureError(Exception):
    pass


def normalized(name, data):
    """A file's bytes as released: text files with "\\n" line endings."""
    return data.replace(b"\r\n", b"\n") if any(name.lower().endswith(s) for s in TEXT) else data


def manifest(tag, version, files):
    """The manifest's exact bytes: {tag, version, files: {"Gargoyle/...": sha256}}, from
    {"Gargoyle/...": released bytes} (one addon's files)."""
    body = {"tag": tag, "version": version,
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    return (json.dumps(body, indent=1, sort_keys=True) + "\n").encode("utf-8")


def app_manifest(tag, app):
    """The app installer's manifest's exact bytes: {kind: "app", tag, version, file, size,
    sha256}, from the release's versions.json entry for the app."""
    body = {"kind": "app", "tag": tag, **{k: app[k] for k in ("version", "file", "size", "sha256")}}
    return (json.dumps(body, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _signed(manifest_bytes, signature, public_key):
    """The manifest's contents, if `signature` (base64 text or bytes) is the release key's
    signature of exactly these bytes; SignatureError otherwise."""
    if not public_key:
        raise SignatureError("this copy of the app has no release key to check updates with")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        raw = base64.b64decode(signature.strip() if isinstance(signature, (bytes, str)) else b"", validate=True)
        key.verify(raw, manifest_bytes)
    except (InvalidSignature, ValueError, TypeError):
        raise SignatureError("the release isn't signed by Gargoyle's release key") from None
    try:
        body = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SignatureError("the signed manifest can't be read") from None
    if not isinstance(body, dict) or not isinstance(body.get("version"), str) or not isinstance(body.get("tag"), str):
        raise SignatureError("the signed manifest can't be read")
    return body


def verify(manifest_bytes, signature, public_key):
    """An addon's manifest, if `signature` (base64 text or bytes) is the release key's
    signature of exactly these bytes; SignatureError otherwise."""
    body = _signed(manifest_bytes, signature, public_key)
    files = body.get("files")
    if ("kind" in body or not isinstance(files, dict) or not files
            or not all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 for k, v in files.items())):
        raise SignatureError("the signed manifest can't be read")
    return body


def verify_app(manifest_bytes, signature, public_key):
    """The app installer's manifest (app_manifest), if the release key signed exactly these
    bytes; SignatureError otherwise."""
    body = _signed(manifest_bytes, signature, public_key)
    size, sha256 = body.get("size"), body.get("sha256")
    if (body.get("kind") != "app" or not isinstance(body.get("file"), str) or not isinstance(size, int)
            or isinstance(size, bool) or size <= 0 or not isinstance(sha256, str) or len(sha256) != 64):
        raise SignatureError("the signed manifest can't be read")
    return body
