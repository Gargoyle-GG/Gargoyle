"""What the Gargoyle app does, without its window (tested in tests/test_helper.py).

- Linking: asks the website for a code, then waits until someone approves it (app_api.py).
- Sending: reads the Gargoyle addon's saved file(s) when the game rewrites them (on
  /reload or logout) and sends signups made in game that weren't sent yet, and the
  characters picked in game whenever the addon has read them again.
- Fetching: gets your raids from the website and writes them into the Gargoyle_Sync data
  addon, which the game loads the next time you log in or /reload.
- Versions: reads which addon and app versions are current from the latest GitHub release,
  and downloads the addon from it (installed by addon_install.py).

It only ever touches the Gargoyle addon's saved data, the Gargoyle_Sync folder and (when
installing or updating it) the Gargoyle addon's own folder.
"""
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

import addon_install
import signing
import sync_file
import wow_paths
from lua_io import LuaError, read_saved
from version import ADDON_SIGNING_KEY, APP_VERSION, RELEASES

REFRESH_SECONDS = 300  # fetch raids at least this often
SENT_KEEP_DAYS = 30
BATCH = 50  # the website takes up to 50 signups at once
CHARACTER_BATCH = 10  # and up to 10 characters
TIMEOUT = 20
MAX_SAVED_BYTES = 20 * 1024 * 1024  # (lua_io's limit too; checked before the file is read in)


class Unlinked(Exception):
    """The website no longer accepts this app's token (unlinked on the website)."""


def safe_site(url):
    """Tokens only travel over https (or to this PC, for trying the website locally)."""
    parts = urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1"))


class Syncer:
    def __init__(self, config, http=None, log=print):
        self.config = config
        self.http = http or requests.Session()
        self.log = log
        self.seen = {}  # saved file -> when it last changed, as last checked
        self.last_refresh = 0
        self.retry_at = 0  # after a failed try (offline), not before this
        self.talking = threading.Lock()  # (syncing, linking and update checks run side by side: one request at a time)
        # What the window shows: the GargoyleSync table last written for the game, and the
        # signups and picked characters last read from the game's saved files.
        self.table = None
        self.actions, self.picked = [], []

    # ---- Talking to the website ----

    def _url(self, path):
        site = self.config.site
        if not safe_site(site):
            raise ValueError(f"refusing to send the account token to {site}: not https")
        return site + path

    def _call(self, method, path, auth=True, **kwargs):
        headers = {"User-Agent": f"GargoyleApp/{APP_VERSION}"}
        token = self.config.token if auth else None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with self.talking:
            response = self.http.request(method, self._url(path), headers=headers, timeout=TIMEOUT, **kwargs)
        if response.status_code == 401 and token:
            raise Unlinked()
        response.raise_for_status()
        return response.json()

    def start_link(self, pc_name=None):
        """{"user_code", "verify_url", "device_code", "interval", "expires_in"}. The page to
        open is always the website's own /link, where you paste the code (it's never put in
        the address: see app_api.py)."""
        answer = self._call("POST", "/api/app/link", json={"name": (pc_name or os.environ.get("COMPUTERNAME") or "PC")[:60]})
        code = answer.get("user_code") if isinstance(answer, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", code) \
                or not isinstance(answer.get("device_code"), str):
            raise ValueError("the website's answer didn't make sense")
        answer["verify_url"] = f"{self.config.site}/link"
        return answer

    def finish_link(self, device_code):
        """"pending", "expired", or "linked" (and the token is saved)."""
        answer = self._call("POST", "/api/app/token", json={"device_code": device_code})
        if answer.get("status") == "linked" and answer.get("token"):
            self.config.token = answer["token"]
            self.config.set("user", answer.get("user") or "")
        return answer.get("status", "expired")

    def versions(self):
        """What the latest release has (its versions.json; see addon_install.py)."""
        answer = json.loads(self.fetch(f"{RELEASES}/latest/download/versions.json", addon_install.MAX_VERSIONS))
        return answer if isinstance(answer, dict) else {}

    def signed_addon(self, offer):
        """The release's signed addon manifest (signing.py), checked against the release
        key, for the addon `offer` (addon_install.offer). SignatureError if it isn't right."""
        base = f"{RELEASES}/download/{offer['tag']}/"
        body = self.fetch(base + signing.MANIFEST, 256 * 1024)
        signature = self.fetch(base + signing.SIGNATURE, 1024)
        signed = signing.verify(body, signature, ADDON_SIGNING_KEY)
        if signed["version"] != offer["version"] or signed["tag"] != offer["tag"]:
            raise signing.SignatureError("the signed manifest is for a different release")
        return signed

    def download(self, url, limit):
        """A file from a release (its address from addon_install), up to `limit` bytes."""
        if not url.startswith(RELEASES + "/download/"):
            raise addon_install.InstallError("that isn't a Gargoyle release")
        return self.fetch(url, limit)

    def fetch(self, url, limit):
        """A file from GitHub's releases, which never gets the account token. GitHub sends
        downloads on to its file servers; anywhere else is refused."""
        with self.talking:
            response = self.http.request("GET", url, headers={"User-Agent": f"GargoyleApp/{APP_VERSION}"},
                                         timeout=TIMEOUT, stream=True)
            response.raise_for_status()
            if not addon_install.from_github(getattr(response, "url", url)):
                raise addon_install.InstallError("the download came from somewhere unexpected")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data += chunk
                if len(data) > limit:
                    raise addon_install.InstallError("the download is bigger than expected")
            return bytes(data)

    def unlink(self):
        try:
            if self.config.token:
                self._call("DELETE", "/api/app/token")
        except (requests.RequestException, Unlinked):
            pass  # (gone already, or offline: forgetting it here is what matters)
        self.config.token = None

    # ---- The game's files ----

    @property
    def game_folder(self):
        folder = self.config.get("game_folder")
        return Path(folder) if folder else None

    def read_saved(self):
        """From every WoW account's saved file: the in-game signups, the picked characters
        (the latest copy of each), and the files' change times."""
        actions, characters, stamps = {}, {}, {}
        for path in wow_paths.saved_files(self.game_folder):
            try:
                info = path.stat()
                stamps[str(path)] = info.st_mtime
                if info.st_size > MAX_SAVED_BYTES:
                    raise LuaError("it's far bigger than Gargoyle's saved data should be")
                saved = read_saved(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, LuaError) as exc:
                self.log(f"Couldn't read {path.name} ({exc}); trying again next time.")
                continue
            for action in sync_file.outbox(saved):
                actions[action["id"]] = action
            for c in sync_file.characters(saved):
                if c["key"] not in characters or c["at"] > characters[c["key"]]["at"]:
                    characters[c["key"]] = c
        self.actions, self.picked = list(actions.values()), list(characters.values())
        return self.actions, self.picked, stamps

    def load_last(self):
        """When the app starts: what the game has (the data file written last time, and the
        saved files), for the window to show before the first sync."""
        if not self.game_folder:
            return
        data = self.game_folder / "Interface" / "AddOns" / "Gargoyle_Sync" / "Data.lua"
        try:
            if data.stat().st_size > MAX_SAVED_BYTES:
                raise LuaError("far bigger than the app ever writes it")
            table = read_saved(data.read_text(encoding="utf-8")).get("GargoyleSync")
            self.table = table if isinstance(table, dict) else None
        except (OSError, LuaError):
            self.table = None
        self.read_saved()

    def send_characters(self, characters):
        """Sends the picked characters the website hasn't had this copy of. Returns what it
        said about each picked one ({key: "saved" / "limit" / ...}) and how many were saved."""
        stored = self.config.get("uploaded")
        uploaded = {k: v for k, v in (stored if isinstance(stored, dict) else {}).items()
                    if isinstance(v, dict) and isinstance(v.get("result"), str)}
        new = [c for c in characters if uploaded.get(c["key"], {}).get("at") != c["at"]]
        saved = 0
        for i in range(0, len(new), CHARACTER_BATCH):
            batch = new[i:i + CHARACTER_BATCH]
            answer = self._call("POST", "/api/app/characters", json={"characters": batch})
            results = {r.get("key"): str(r.get("result")) for r in (answer.get("results", []) if isinstance(answer, dict) else [])
                       if isinstance(r, dict) and isinstance(r.get("key"), str)}
            for c in batch:
                if c["key"] in results:
                    uploaded[c["key"]] = {"at": c["at"], "result": results[c["key"]]}
                    if results[c["key"]] == "saved":
                        saved += 1
            self.config.set("uploaded", uploaded)
        # Only the characters still picked are worth remembering.
        picked = {c["key"] for c in characters}
        uploaded = {k: v for k, v in uploaded.items() if k in picked}
        self.config.set("uploaded", uploaded)
        return {k: v["result"] for k, v in uploaded.items()}, saved

    def write_sync(self, api, done, imports=None):
        """Gargoyle_Sync/Data.lua (and its .toc), written whole: a temporary file first,
        then swapped in, so the game never loads half a file."""
        folder = self.game_folder / "Interface" / "AddOns" / "Gargoyle_Sync"
        folder.mkdir(parents=True, exist_ok=True)
        self.table = sync_file.sync_table(api, done, imports)
        files = {"Data.lua": sync_file.sync_lua(api, done, imports)}
        interface = wow_paths.interface_version(self.game_folder)
        if interface:
            files["Gargoyle_Sync.toc"] = sync_file.toc(interface)
        for name, text in files.items():
            target = folder / name
            try:
                if target.read_text(encoding="utf-8") == text:
                    continue  # unchanged: leave the file alone
            except (OSError, UnicodeDecodeError):
                pass
            temp = folder / (name + ".tmp")
            temp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(temp, target)

    # ---- One round ----

    def changed(self):
        """Has the game rewritten a saved file since last time?"""
        if not self.game_folder:
            return False
        stamps = {}
        for path in wow_paths.saved_files(self.game_folder):
            try:
                stamps[str(path)] = path.stat().st_mtime
            except OSError:
                pass
        return stamps != self.seen

    def due(self):
        if time.time() < self.retry_at:
            return False
        return time.time() - self.last_refresh >= REFRESH_SECONDS or self.changed()

    def run(self):
        """Send new signups and characters, then fetch raids and write them for the game.
        Returns a short summary. Raises Unlinked, or requests' errors when offline."""
        if not self.config.token:
            raise Unlinked()
        if not self.game_folder:
            raise ValueError("choose the game folder first")
        if addon_install.installed_version(self.game_folder) is None:
            raise ValueError("install the Gargoyle addon first")
        actions, characters, stamps = self.read_saved()
        stored = self.config.get("sent")
        sent = {k: v for k, v in (stored if isinstance(stored, dict) else {}).items()
                if isinstance(v, dict) and isinstance(v.get("result"), str)}
        new = [a for a in actions if a["id"] not in sent]
        for i in range(0, len(new), BATCH):
            answer = self._call("POST", "/api/app/signups", json={"actions": new[i:i + BATCH]})
            for result in answer.get("results", []) if isinstance(answer, dict) else []:
                if isinstance(result, dict) and isinstance(result.get("id"), str):
                    sent[result["id"]] = {"result": str(result.get("result")), "at": int(time.time())}
            self.config.set("sent", sent)  # kept straight away, so nothing is sent twice if the next step fails
        imports, characters_saved = self.send_characters(characters)
        api = self._call("GET", "/api/app/sync")
        if not isinstance(api, dict):
            raise ValueError("the website's answer didn't make sense")
        # What the addon may let go of: everything answered that's still in an outbox.
        waiting = {a["id"] for a in actions}
        done = {k: v["result"] for k, v in sent.items() if k in waiting}
        self.write_sync(api, done, imports)
        # Forget answers the addon has let go of, after a while.
        cutoff = time.time() - SENT_KEEP_DAYS * 86400
        self.config.set("sent", {k: v for k, v in sent.items() if k in waiting or v.get("at", 0) > cutoff})
        self.seen, self.last_refresh = stamps, time.time()
        guilds = api.get("guilds") if isinstance(api.get("guilds"), list) else []
        raids = sum(len(g.get("raids") or []) for g in guilds if isinstance(g, dict))
        saved = sum(1 for a in new if sent.get(a["id"], {}).get("result") == "saved")
        summary = f"{raids} upcoming raid{'s' if raids != 1 else ''}"
        if saved:
            summary += f", {saved} signup{'s' if saved != 1 else ''} sent"
        if characters_saved:
            summary += f", {characters_saved} character{'s' if characters_saved != 1 else ''} updated"
        return summary
