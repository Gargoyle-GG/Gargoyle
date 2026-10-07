"""The Gargoyle app's version. Raise it for every app release (helper/build.py reads it, and
the release's tag is made from it), so the apps already out there can say a new one is ready."""
APP_VERSION = "1.5.0"

# Where the app and the addon are released: GitHub builds both from the public source code
# there (helper/build.py, run by .github/workflows/release.yml) and posts them as a release.
REPO = "Gargoyle-GG/Gargoyle"
RELEASES = f"https://github.com/{REPO}/releases"
# The signed app installer manifest (signing.py), in the public repo once GitHub has built a release.
SIGNED = f"https://raw.githubusercontent.com/{REPO}/main/release"

# The public half of Gargoyle's release key (helper/signing.py): addon updates are only
# installed, and app updates only run, if this key signed them. Its private half never goes
# near GitHub.
ADDON_SIGNING_KEY = "0cJL/l5MqwGcXt6s2mNSH2iIzi8aCJ/iyDsr+Tt99Wg="
