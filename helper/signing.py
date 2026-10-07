"""Signed addon releases: the app only installs addon files that Gargoyle's release key signed.

GitHub builds every release from the public code, but a GitHub account can be broken into.
So each release also carries addon-manifest.json (every addon file with its SHA-256) and
addon-manifest.sig, an Ed25519 signature over that file made with a key that never goes near
GitHub. The app checks the signature against the public key in version.py, then checks every
file it unpacks against the manifest, and installs nothing that doesn't match. Someone who
got into GitHub could post a release, but not one the app would install.

The manifest is made from the code (build.py, with text files' line endings made "\\n" so
any checkout gives the same bytes), so anyone can check a release's manifest against the
public code at its tag.
"""
import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST = "addon-manifest.json"
SIGNATURE = "addon-manifest.sig"
# Each addon's own manifest and signature ("addon": Gargoyle, "tooltips": Gargoyle_Tooltips).
MANIFESTS = {"addon": (MANIFEST, SIGNATURE), "tooltips": ("tooltips-manifest.json", "tooltips-manifest.sig")}
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


def verify(manifest_bytes, signature, public_key):
    """The manifest, if `signature` (base64 text or bytes) is the release key's signature of
    exactly these bytes; SignatureError otherwise."""
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
    files = body.get("files") if isinstance(body, dict) else None
    if (not isinstance(files, dict) or not files or not isinstance(body.get("version"), str)
            or not isinstance(body.get("tag"), str)
            or not all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 for k, v in files.items())):
        raise SignatureError("the signed manifest can't be read")
    return body
