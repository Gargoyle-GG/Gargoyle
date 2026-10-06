"""The Gargoyle app (helper/): Lua in and out, settings, and a whole round trip between the
website, the app and the addon."""
import re
import sys
import time
from pathlib import Path

import pytest
import requests

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "helper"))
import addon_install  # noqa: E402
import overview  # noqa: E402
import signing  # noqa: E402
import sync  # noqa: E402
import startup  # noqa: E402
import sync_file  # noqa: E402
import wow_paths  # noqa: E402
from config import Config  # noqa: E402
from lua_io import LuaError, read_saved, to_lua  # noqa: E402
from sync import Syncer, safe_site  # noqa: E402

lupa = pytest.importorskip("lupa")
from lupa import lua51  # noqa: E402

HOSTILE = [
    '"]] os.exit() --', '\\" .. pwned() .. "', "line\nbreak", "tab\tand\rreturn", "nul\0byte", "\x1b[31m\x7f",
    "\\", '\\"', "]]", "[==[", "--[[", "ünïcødé ✓ 漢字", "|cffff0000|Hitem:1|h[x]|h|r", "\ud800 lone surrogate",
]

# The game writes SavedVariables much like this (strings with %q, so a newline is a
# backslash followed by a real newline).
SERIALIZE = r"""
function serialize(v, indent)
  indent = indent or ""
  if type(v) == "table" then
    local lines = { "{" }
    for k, x in pairs(v) do
      local key = type(k) == "string" and string.format("[%q]", k) or "[" .. tostring(k) .. "]"
      table.insert(lines, indent .. "\t" .. key .. " = " .. serialize(x, indent .. "\t") .. ",")
    end
    table.insert(lines, indent .. "}")
    return table.concat(lines, "\n")
  elseif type(v) == "string" then
    return string.format("%q", v)
  end
  return tostring(v)
end
"""


def load_in_lua(source):
    """Run written Lua in an empty sandbox (nothing to call) and hand back GargoyleSync."""
    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    run = lua.eval("function(src) local env = {}; local f = assert(loadstring(src)); setfenv(f, env); f(); return env end")
    return run(source)


def test_hostile_text_stays_text():
    data = {"title": HOSTILE, "keys": {s: i for i, s in enumerate(HOSTILE) if "\ud800" not in s}}
    env = load_in_lua("GargoyleSync = " + to_lua(data))
    titles = list(env.GargoyleSync.title.values())
    assert titles[:13] == HOSTILE[:13]  # exactly as given
    assert titles[13] == "? lone surrogate"  # (a broken character is replaced)
    assert {k: v for k, v in env.GargoyleSync["keys"].items()} == data["keys"]


def test_writer_refuses_anything_but_data():
    for bad in (object(), {1.5: "x"}, {True: 1}, [None], {"f": print}):
        with pytest.raises(LuaError):
            to_lua(bad)
    nested = []
    for _ in range(40):
        nested = [nested]
    with pytest.raises(LuaError):
        to_lua(nested)
    assert to_lua({"a": None, "end": 1, "ok_name": float("nan")}) == '{\n  ["end"] = 1,\n  ok_name = 0,\n}'


def test_reading_saved_variables():
    lua = lua51.LuaRuntime()
    lua.execute(SERIALIZE)
    lua.execute('GargoyleDB = { modules = { raids = false }, outbox = { { id = "a1", raid = 3, note = "two\\nlines \\"q\\" \\0 ✓", at = 1800000000 } } }')
    text = "GargoyleDB = " + lua.eval("serialize(GargoyleDB)") + "\n"
    saved = read_saved(text)
    assert saved["GargoyleDB"]["modules"] == {"raids": False}
    assert saved["GargoyleDB"]["outbox"] == [{"id": "a1", "raid": 3, "note": 'two\nlines "q" \0 ✓', "at": 1800000000}]
    assert read_saved("A = {}\nB = { [1] = 'x' }".replace("'", '"')) == {"A": {}, "B": ["x"]}
    assert read_saved("X = { 1, 2, nil, -3.5, 0x10, 1e3 } -- comment") == {"X": {1: 1, 2: 2, 4: -3.5, 5: 16, 6: 1000}}


def test_reading_refuses_code():
    for bad in ("X = os.exit()", "X = function() end", "X = 1 + 2", "X = Y", "os.exit()", "X = { [{}] = 1 }",
                "return 1", 'X = "unterminated', "X = { 1 2 }", 'X = "\\q"', 'X = "\\999"'):
        with pytest.raises((LuaError, TypeError)):
            read_saved(bad)
    with pytest.raises(LuaError):
        read_saved("X = " + "{" * 40 + "}" * 40)


def test_outbox_from_saved_data():
    saved = {"GargoyleDB": {"outbox": [{"id": "a", "raid": 1, "character": 2, "status": "accepted", "role": "dps",
                                        "note": "hi", "at": 5, "title": "MC"}, {"id": 7}, "junk", {"raid": 1}]}}
    assert sync_file.outbox(saved) == [{"id": "a", "raid": 1, "character": 2, "status": "accepted", "role": "dps",
                                        "note": "hi", "at": 5}]
    assert sync_file.outbox({"GargoyleDB": {"outbox": {}}}) == [] and sync_file.outbox({}) == []


def test_tokens_only_go_over_https():
    assert safe_site("https://gargoyle.gg") and safe_site("http://localhost:5000")
    assert not safe_site("http://gargoyle.gg") and not safe_site("ftp://localhost")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' DPAPI")
def test_token_is_encrypted_on_disk(tmp_path):
    config = Config(tmp_path / "config.json")
    config.token = "secret-token-123"
    assert "secret-token-123" not in (tmp_path / "config.json").read_text()
    assert Config(tmp_path / "config.json").token == "secret-token-123"
    config.token = None
    assert Config(tmp_path / "config.json").token is None


def test_finding_the_game_folder(tmp_path):
    install = tmp_path / "World of Warcraft"
    toc = install / "_classic_beta_" / "Interface" / "AddOns" / "Gargoyle" / "Gargoyle.toc"
    toc.parent.mkdir(parents=True)
    toc.write_text("## Interface: 16001\n## Title: Gargoyle\n")
    (install / "_retail_" / "Interface" / "AddOns").mkdir(parents=True)
    assert wow_paths.game_folders(install) == [install / "_classic_beta_"]
    assert wow_paths.game_folders(install / "_classic_beta_") == [install / "_classic_beta_"]
    assert wow_paths.interface_version(install / "_classic_beta_") == "16001"


# ---- The whole round trip ----


@pytest.fixture
def game_folder(tmp_path):
    folder = tmp_path / "World of Warcraft" / "_classic_beta_"
    addon = folder / "Interface" / "AddOns" / "Gargoyle"
    addon.mkdir(parents=True)
    (addon / "Gargoyle.toc").write_text((PROJECT / "addon" / "Gargoyle" / "Gargoyle.toc").read_text())
    (folder / "WTF" / "Account" / "123#1" / "SavedVariables").mkdir(parents=True)
    return folder


def save_game(game, folder):
    """What the game does on /reload: write GargoyleDB to the saved file."""
    game.lua.execute(SERIALIZE)
    text = "\nGargoyleDB = " + game.lua.eval("serialize(GargoyleDB)") + "\n"
    (folder / "WTF" / "Account" / "123#1" / "SavedVariables" / "Gargoyle.lua").write_text(text, encoding="utf-8")


def test_characters_from_saved_data():
    saved = {"GargoyleDB": {"characters": {
        "Player-1-1": {"picked": 5, "at": 9, "name": "A", "class": "MAGE", "level": 60, "evil": "x",
                       "talents": [{"tab": 1, "row": 1, "col": 1, "rank": 1, "name": "N" * 99}, "junk"],
                       "gear": {"1": "not a list"}, "skills": [{"name": "Tailoring", "rank": "lots"}]},
        "Player-1-2": {"picked": 5, "name": "Not read yet"},
        "x" * 81: {"picked": 5, "at": 9, "name": "Key too long"},
        7: {"picked": 5, "at": 9, "name": "Odd key"},
        "Player-1-3": "junk",
    }}}
    (c,) = sync_file.characters(saved)
    assert c["key"] == "Player-1-1" and "evil" not in c
    assert c["talents"] == [{"tab": 1, "row": 1, "col": 1, "rank": 1, "name": "N" * 60, "spell": None}]
    assert c["gear"] is None and c["skills"] == [{"name": "Tailoring", "rank": None}]
    assert sync_file.characters({"GargoyleDB": {"characters": []}}) == [] and sync_file.characters({}) == []


def test_outbox_skips_ids_the_website_would_refuse():
    saved = {"GargoyleDB": {"outbox": [{"id": "x" * 41, "raid": 1}, {"id": "bad id!", "raid": 1}, {"id": "ok-1", "raid": 1}]}}
    assert [a["id"] for a in sync_file.outbox(saved)] == ["ok-1"]


def test_answers_are_kept_even_if_fetching_fails(tmp_path, game_folder):
    calls = []

    class Fake:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class Http:
        def request(self, method, url, headers=None, timeout=None, json=None):
            calls.append(url)
            if url.endswith("/api/app/signups"):
                return Fake({"results": [{"id": a["id"], "result": "saved"} for a in json["actions"]]})
            raise requests.ConnectionError("offline")

    (game_folder / "WTF" / "Account" / "123#1" / "SavedVariables" / "Gargoyle.lua").write_text(
        'GargoyleDB = { ["outbox"] = { { ["id"] = "a1", ["raid"] = 1, ["at"] = 1800000000 } } }')
    config = Config(tmp_path / "config.json")
    config.data.update(site="https://gargoyle.gg", game_folder=str(game_folder))
    config.token = "t"
    syncer = Syncer(config, http=Http(), log=lambda text: None)
    with pytest.raises(requests.ConnectionError):
        syncer.run()
    assert Config(tmp_path / "config.json").get("sent")["a1"]["result"] == "saved"
    with pytest.raises(requests.ConnectionError):
        syncer.run()
    assert sum(1 for u in calls if u.endswith("/api/app/signups")) == 1  # not sent twice


def test_unchanged_data_isnt_rewritten(tmp_path, game_folder):
    config = Config(tmp_path / "config.json")
    config.data["game_folder"] = str(game_folder)
    syncer = Syncer(config, log=lambda text: None)
    syncer.write_sync({"user": "A", "time": 1}, {})
    data = game_folder / "Interface" / "AddOns" / "Gargoyle_Sync" / "Data.lua"
    first = data.stat().st_mtime_ns
    time.sleep(0.02)
    syncer.write_sync({"user": "A", "time": 1}, {})
    assert data.stat().st_mtime_ns == first
    syncer.write_sync({"user": "B", "time": 1}, {})
    assert '"B"' in data.read_text(encoding="utf-8")


# ---- Installing and updating the addon ----

def addon_zip(files=None, version=None):
    """The Gargoyle addon zipped like helper/build.py does (or other files)."""
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        if files is None:
            for path in sorted((PROJECT / "addon" / "Gargoyle").rglob("*")):
                if path.is_file():
                    text = path.read_bytes()
                    if version and path.name == "Gargoyle.toc":
                        text = re.sub(rb"## Version: \S+", b"## Version: " + version.encode(), text)
                    z.writestr("Gargoyle/" + path.relative_to(PROJECT / "addon" / "Gargoyle").as_posix(), text)
        else:
            for name, text in files.items():
                z.writestr(name, text)
    return buffer.getvalue()


def offer_for(data, version="9.0.0", file="Gargoyle-addon.zip"):
    """A release file's entry in versions.json."""
    import hashlib
    return {"version": version, "file": file, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def release(addon=b"zip", addon_version="9.0.0", app=b"exe", app_version="9.1.0", tag="v9.1.0-addon9.0.0"):
    """A release's versions.json."""
    return {"tag": tag, "addon": offer_for(addon, addon_version),
            "app": offer_for(app, app_version, "GargoyleSetup.exe")}


def signed_for(data, version="9.0.0", tag="v9.1.0-addon9.0.0"):
    """The signed manifest (as signing.verify returns it) of exactly what a zip holds."""
    import io
    import json
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
    return json.loads(signing.manifest(tag, version, files))


@pytest.fixture
def release_key(monkeypatch):
    """A throwaway release key the app trusts for this test: sign(bytes) -> signature."""
    import base64
    import version
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    monkeypatch.setattr(sync, "ADDON_SIGNING_KEY", public)
    monkeypatch.setattr(version, "ADDON_SIGNING_KEY", public)
    return lambda data: base64.b64encode(private.sign(data)) + b"\n"


def test_installing_and_updating_the_addon(tmp_path):
    game = tmp_path / "_classic_"
    (game / "Interface" / "AddOns" / "Other").mkdir(parents=True)
    assert addon_install.installed_version(game) is None
    data = addon_zip(version="0.9.0")
    addon_install.check_download(data, offer_for(data))
    assert addon_install.install(game, data, signed_for(data, "0.9.0")) == "0.9.0"
    folder = game / "Interface" / "AddOns" / "Gargoyle"
    assert (folder / "Modules" / "Raids.lua").is_file() and (game / "Interface" / "AddOns" / "Other").is_dir()
    # An update replaces the whole folder (a file the new version doesn't have goes), and
    # leftovers from an update that was cut short are cleared away.
    (folder / "Old.lua").write_text("--")
    (game / "Interface" / "AddOns" / "Gargoyle.new").mkdir()
    newer = addon_zip(version="1.0.0")
    assert addon_install.install(game, newer, signed_for(newer, "1.0.0")) == "1.0.0"
    assert not (folder / "Old.lua").exists() and wow_paths.has_addon(game)
    assert sorted(p.name for p in (game / "Interface" / "AddOns").iterdir()) == ["Gargoyle", "Other"]

    # A download that didn't arrive whole, or isn't what the website said, is refused.
    with pytest.raises(addon_install.InstallError):
        addon_install.check_download(data[:-1], offer_for(data))
    with pytest.raises(addon_install.InstallError):
        addon_install.check_download(data, {**offer_for(data), "sha256": "0" * 64})
    # Anything that would unpack outside the Gargoyle folder, or isn't the addon, is
    # refused, and the installed copy stays as it was.
    for files in ({"Gargoyle/Gargoyle.toc": "x", "Gargoyle/../Evil/Evil.toc": "x"},
                  {"Gargoyle/Gargoyle.toc": "x", "Other/Other.toc": "x"},
                  {"Gargoyle/Gargoyle.toc": "x", "/abs.lua": "x"},
                  {"Gargoyle/Gargoyle.toc": "x", "Gargoyle/C:evil.lua": "x"},
                  {"Gargoyle/Gargoyle.toc": "x", "Gargoyle/CON": "x"}, {"Gargoyle/Gargoyle.toc": "x", "Gargoyle/nul.lua": "x"},
                  {"Gargoyle/Gargoyle.toc": "x", "Gargoyle/a.lua.": "x"}, {"Gargoyle/Gargoyle.toc": "x", "Gargoyle/..\\x.lua": "x"},
                  {"Gargoyle/Core.lua": "x"},
                  {"Gargoyle/Gargoyle.toc": "x" * (addon_install.MAX_UNPACKED + 1)}):
        with pytest.raises(addon_install.InstallError):
            addon_install.install(game, addon_zip(files), signed_for(newer))
    with pytest.raises(addon_install.InstallError):
        addon_install.install(game, b"not a zip", signed_for(newer))
    # Only exactly the signed files: one changed, one extra, one missing, or no manifest at all.
    import io
    import zipfile

    def changed(edit):
        files = {}
        with zipfile.ZipFile(io.BytesIO(newer)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        edit(files)
        return addon_zip(files)
    for bad in (changed(lambda f: f.update({"Gargoyle/Core.lua": f["Gargoyle/Core.lua"] + b"\nSendChatMessage('pwned')"})),
                changed(lambda f: f.update({"Gargoyle/Evil.lua": b"--"})),
                changed(lambda f: f.pop("Gargoyle/Debug.lua"))):
        with pytest.raises(addon_install.InstallError, match="signed release"):
            addon_install.install(game, bad, signed_for(newer))
    for signed in (None, {}, {"files": "x"}):
        with pytest.raises(addon_install.InstallError, match="signed release"):
            addon_install.install(game, newer, signed)
    assert addon_install.installed_version(game) == "1.0.0" and not (tmp_path / "Evil").exists()
    assert sorted(p.name for p in (game / "Interface" / "AddOns").iterdir()) == ["Gargoyle", "Other"]


def test_a_linked_addon_folder_is_left_alone(tmp_path):
    _winapi = pytest.importorskip("_winapi")
    source = tmp_path / "repo" / "Gargoyle"
    source.mkdir(parents=True)
    (source / "Gargoyle.toc").write_text("## Version: 0.1.0\n")
    game = tmp_path / "_classic_"
    (game / "Interface" / "AddOns").mkdir(parents=True)
    _winapi.CreateJunction(str(source), str(game / "Interface" / "AddOns" / "Gargoyle"))
    assert addon_install.is_linked(game / "Interface" / "AddOns" / "Gargoyle") and not addon_install.is_linked(source)
    with pytest.raises(addon_install.InstallError):
        addon_install.install(game, addon_zip(), signed_for(addon_zip()))
    assert (source / "Gargoyle.toc").read_text() == "## Version: 0.1.0\n" and len(list(source.iterdir())) == 1


def test_versions():
    assert addon_install.newer("0.10.0", "0.9.9") and addon_install.newer("1.0", None) and addon_install.newer("1.0", "?")
    assert not addon_install.newer("0.4.0", "0.4.0") and not addon_install.newer("0.3", "0.4.0")
    assert not addon_install.newer("1.0-evil", "0.1") and not addon_install.newer(None, "0.1")
    from version import RELEASES
    assert addon_install.app_update(release(app_version="1.2.0"), "1.1.0") == "1.2.0"
    assert addon_install.app_update(release(app_version="1.1.0"), "1.1.0") is None
    assert addon_install.app_update({}, "1.1.0") is None and addon_install.app_update("junk", "1.1.0") is None
    assert addon_install.app_download(release()) == f"{RELEASES}/download/v9.1.0-addon9.0.0/GargoyleSetup.exe"
    good = release()
    assert addon_install.offer(good) == {**good["addon"], "tag": "v9.1.0-addon9.0.0",
                                         "url": f"{RELEASES}/download/v9.1.0-addon9.0.0/Gargoyle-addon.zip"}
    for bad in ({"file": "../x.zip"}, {"file": "x.exe"}, {"file": "a/b.zip"}, {"sha256": "abc"},
                {"size": addon_install.MAX_DOWNLOAD + 1}, {"size": "3"}, {"size": True}, {"version": "new"}):
        assert addon_install.offer({**good, "addon": {**good["addon"], **bad}}) is None
    for tag in ("../x", "a/b", "", None, "x" * 61):
        assert addon_install.offer({**good, "tag": tag}) is None and addon_install.app_download({**good, "tag": tag}) is None
    assert addon_install.app_download({**good, "app": {**good["app"], "file": "Setup.zip"}}) is None
    # Downloads only ever come from GitHub (which sends them on to its file servers).
    assert addon_install.from_github("https://github.com/x") and addon_install.from_github("https://objects.githubusercontent.com/x")
    for url in ("http://github.com/x", "https://github.com.evil.example/x", "https://evil.example/github.com", "file:///c:/x"):
        assert not addon_install.from_github(url)


class FakeGitHub:
    """GitHub's releases, as requests sees them: files, and where they ended up after redirects."""

    def __init__(self, files, land="https://release-assets.githubusercontent.com/x"):
        self.files, self.land, self.asked = files, land, []

    def request(self, method, url, headers=None, **kw):
        self.asked.append((url, dict(headers or {})))
        name = url.rsplit("/", 1)[1]
        data, land = self.files.get(name), self.land

        class Answer:
            status_code = 200 if data is not None else 404
            url = land

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(self.status_code)

            def iter_content(self, size):
                return (data[i:i + size] for i in range(0, len(data), size))
        return Answer()


def test_the_app_installs_the_addon_from_a_github_release(tmp_path, game_folder, release_key):
    import io
    import json
    import zipfile
    from version import RELEASES
    data = addon_zip(version="9.0.0")
    versions = release(addon=data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = signing.manifest("v9.1.0-addon9.0.0", "9.0.0", {n: z.read(n) for n in z.namelist()})
    github = FakeGitHub({"versions.json": json.dumps(versions).encode(), "Gargoyle-addon.zip": data,
                         "addon-manifest.json": body, "addon-manifest.sig": release_key(body)})
    config = Config(tmp_path / "config.json")
    config.data.update(game_folder=str(game_folder))
    config.token = "secret"
    syncer = Syncer(config, http=github, log=lambda text: None)
    assert syncer.versions() == versions
    offer = addon_install.offer(syncer.versions())
    signed = syncer.signed_addon(offer)
    download = syncer.download(offer["url"], addon_install.MAX_DOWNLOAD)
    addon_install.check_download(download, offer)
    assert addon_install.install(game_folder, download, signed) == "9.0.0"
    assert github.asked[0][0] == f"{RELEASES}/latest/download/versions.json"
    assert all("Authorization" not in headers for _, headers in github.asked)  # (the account token stays with gargoyle.gg)
    with pytest.raises(addon_install.InstallError):
        syncer.download(offer["url"], 10)
    with pytest.raises(addon_install.InstallError):
        syncer.download("https://evil.example/Gargoyle-addon.zip", addon_install.MAX_DOWNLOAD)
    # Sent on somewhere other than GitHub's file servers: refused.
    elsewhere = Syncer(config, http=FakeGitHub(github.files, land="https://evil.example/x"), log=lambda text: None)
    with pytest.raises(addon_install.InstallError):
        elsewhere.versions()
    # Someone with access to GitHub but not the release key: their manifest isn't signed by it,
    # a signature from another key doesn't count, and a real one can't be reused for another release.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    forged_body = body.replace(b'"9.0.0"', b'"9.0.1"')
    for files in ({**github.files, "addon-manifest.json": forged_body},
                  {**github.files, "addon-manifest.sig": base64.b64encode(Ed25519PrivateKey.generate().sign(body))},
                  {**github.files, "addon-manifest.sig": b"junk"},
                  {**github.files, "addon-manifest.sig": b""}):
        with pytest.raises(signing.SignatureError):
            Syncer(config, http=FakeGitHub(files), log=lambda text: None).signed_addon(offer)
    with pytest.raises(signing.SignatureError, match="different release"):
        syncer.signed_addon({**offer, "version": "9.0.1"})
    # No release yet (or offline): just an error for the caller to shrug off.
    with pytest.raises(requests.HTTPError):
        Syncer(config, http=FakeGitHub({}), log=lambda text: None).versions()


def test_building_the_addon_zip(tmp_path):
    import hashlib
    import importlib.util
    import json
    import zipfile
    spec = importlib.util.spec_from_file_location("build", PROJECT / "helper" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    first = build.build_addon(tmp_path / "a").read_bytes()
    assert build.build_addon(tmp_path / "b").read_bytes() == first  # (the same code, the same zip)
    with zipfile.ZipFile(tmp_path / "a" / "Gargoyle-addon.zip") as z:
        assert "Gargoyle/Gargoyle.toc" in z.namelist() and all(n.startswith("Gargoyle/") for n in z.namelist())
    # Text files go out with "\n" line endings, whatever the checkout has (so the signed
    # manifest made on a PC matches the addon GitHub builds).
    with zipfile.ZipFile(tmp_path / "a" / "Gargoyle-addon.zip") as z:
        assert all(b"\r\n" not in z.read(n) for n in z.namelist() if n.endswith((".lua", ".toc")))
        assert json.loads(build.addon_manifest("t"))["files"] == {
            n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}
    entry = build.entry(tmp_path / "a" / "Gargoyle-addon.zip", build.addon_version())
    tag = build.release_tag()
    assert addon_install.offer({"tag": tag, "addon": entry})["version"] == build.addon_version()
    assert tag == f"v{build.app_version()}-addon{build.addon_version()}"


def test_syncing_needs_the_addon_installed(tmp_path):
    game = tmp_path / "_classic_"
    game.mkdir()
    config = Config(tmp_path / "config.json")
    config.data["game_folder"] = str(game)
    config.token = "t"
    with pytest.raises(ValueError, match="install the Gargoyle addon"):
        Syncer(config, log=lambda text: None).run()


def test_finding_game_folders_without_the_addon(tmp_path):
    install = tmp_path / "World of Warcraft"
    for name in ("_classic_", "_retail_", "Data"):
        (install / name).mkdir(parents=True)
    assert [f.name for f in wow_paths.version_folders(install)] == ["_classic_", "_retail_"]
    assert wow_paths.version_folders(install / "_classic_") == [install / "_classic_"]
    assert wow_paths.version_folders(tmp_path / "missing") == [] and wow_paths.game_folders(install) == []


# ---- Starting with Windows ----

def test_starting_with_windows(monkeypatch):
    if not startup.available():
        pytest.skip("Windows only")
    import winreg
    monkeypatch.setattr(startup, "RUN_KEY", r"Software\GargoyleTests\Run")
    try:
        assert not startup.enabled()
        startup.set_enabled(True)
        assert startup.enabled()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN_KEY) as key:
            command = winreg.QueryValueEx(key, "Gargoyle")[0]
        assert command.endswith('gargoyle_app.py" --tray') and "pythonw.exe" in command.lower()
        startup.set_enabled(False)
        startup.set_enabled(False)  # (already off: fine)
        assert not startup.enabled()
    finally:
        for key in (r"Software\GargoyleTests\Run", r"Software\GargoyleTests"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass


# ---- What the window shows ----

NOW = 1_800_000_000


def sample_table():
    return sync_file.sync_table({
        "user": "A", "time": NOW,
        "characters": [{"id": 10, "name": "Zyzx", "class": "warlock"}, {"id": 11, "name": "Jaina", "class": "mage"}],
        "guilds": [{"id": 1, "name": "Stone Watch", "raids": [
            {"id": 3, "title": "Blackwing Lair", "start": NOW + 7 * 86400, "signups": []},
            {"id": 1, "title": "Molten Core", "start": NOW + 86400, "size": 40,
             "signups": [{"name": "Someone", "status": "accepted"},
                         {"name": "Zyzx", "status": "accepted", "role": "dps", "mine": True, "character": 10}]},
            {"id": 2, "title": "Started ages ago", "start": NOW - 5 * 3600, "signups": []},
            {"id": 4, "title": "Zul'Gurub", "start": NOW + 2 * 86400,
             "signups": [{"name": "Zyzx", "status": "declined", "role": "dps", "mine": True}]}]}]}, {})


def test_the_raids_the_window_shows():
    actions = [{"id": "a", "raid": 3, "character": 11, "status": "tentative", "role": "healer", "at": 5},
               {"id": "b", "raid": 3, "character": 11, "status": "accepted", "role": "healer", "at": 4},
               {"id": "c", "raid": 1, "status": "declined", "at": 9}]
    raids = overview.raids(sample_table(), actions, {"c": {"result": "saved"}}, NOW)
    assert [r["title"] for r in raids] == ["Molten Core", "Zul'Gurub", "Blackwing Lair"]
    mc, zg, bwl = raids
    assert overview.signup_text(mc) == "Coming as Damage on Zyzx" and not mc["waiting"]  # (c was sent)
    assert overview.signup_text(zg) == "Can't come"
    assert overview.signup_text(bwl) == "Tentative as Healer on Jaina" and bwl["waiting"]  # (the latest of a and b)
    assert overview.signup_text(overview.raids(sample_table(), [], {}, NOW)[2]) == "Not signed up"
    assert [len(overview.unsent(actions, {"c": {}}))] == [2]
    assert overview.raids(None, actions, {}, NOW) == [] and overview.raids({"guilds": "junk"}, [], {}, NOW) == []
    assert overview.raid_path(mc) == "/guilds/1#raid-1"
    # A data file that's been tampered with still shows as plain text.
    odd = {"characters": [{"id": "x", "name": 5}], "guilds": [{"id": 1, "name": 7, "raids": [
        {"id": 1, "title": 42, "start": NOW + 60, "size": True,
         "signups": [{"mine": "yes", "status": "accepted"}, {"mine": True, "status": {}, "role": [1], "name": 3}]}]}]}
    (raid,) = overview.raids(odd, [], {}, NOW)
    assert (raid["title"], raid["guild"], raid["size"], raid["status"], raid["character"]) == ("Raid", "", None, None, None)
    assert overview.signup_text(raid) == "Not signed up"
    assert overview.raid_path({**mc, "guild_id": None}) is None and overview.raid_path({**mc, "id": "1#x"}) is None


def test_the_characters_the_window_shows():
    picked = [{"key": "k1", "name": "zyzx", "class": "WARLOCK", "level": 60, "at": 9},
              {"key": "k2", "name": "Alpha", "class": "MAGE", "at": 9},
              {"key": "k3", "name": "Beta", "class": "PRIEST", "at": 9},
              {"key": "k4", "name": "Gamma", "class": None, "at": 9}]
    uploaded = {"k1": {"at": 9, "result": "saved"}, "k2": {"at": 8, "result": "saved"}, "k3": {"at": 9, "result": "limit"},
                "k4": {"at": 9, "result": "something new"}}
    shown = {c["name"]: c for c in overview.characters(picked, uploaded)}
    assert [c["name"] for c in overview.characters(picked, uploaded)] == ["Alpha", "Beta", "Gamma", "zyzx"]
    assert (shown["zyzx"]["state"], shown["zyzx"]["text"], shown["zyzx"]["class"]) == ("ok", "Up to date on gargoyle.gg", "Warlock")
    assert shown["Alpha"]["state"] == "waiting"  # (read again since it was sent)
    assert shown["Beta"]["state"] == "problem" and "50" in shown["Beta"]["text"]
    assert shown["Gamma"]["state"] == "waiting" and shown["Gamma"]["class"] == ""
    assert overview.characters(picked, "junk")[0]["state"] == "waiting"


def test_the_window_shows_the_last_sync_when_the_app_starts(tmp_path, game_folder):
    config = Config(tmp_path / "config.json")
    config.data["game_folder"] = str(game_folder)
    Syncer(config, log=lambda text: None).write_sync({"user": "A", "time": NOW, "guilds": [{"id": 1, "name": "G", "raids": [
        {"id": 1, "title": 'Molten "Core"', "start": NOW, "signups": []}]}]}, {})
    (game_folder / "WTF" / "Account" / "123#1" / "SavedVariables" / "Gargoyle.lua").write_text(
        'GargoyleDB = { ["outbox"] = { { ["id"] = "a1", ["raid"] = 1, ["at"] = 5 } } }')
    later = Syncer(config, log=lambda text: None)
    later.load_last()
    assert later.table["guilds"][0]["raids"][0]["title"] == 'Molten "Core"' and [a["id"] for a in later.actions] == ["a1"]
    (game_folder / "Interface" / "AddOns" / "Gargoyle_Sync" / "Data.lua").write_text("GargoyleSync = os.exit()")
    later.load_last()
    assert later.table is None


def test_the_window(tmp_path, game_folder, monkeypatch):
    tk = pytest.importorskip("tkinter")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("GARGOYLE_SITE", "https://gargoyle.gg")
    import gargoyle_app
    monkeypatch.setattr(gargoyle_app.App, "start_tray", lambda self: None)
    monkeypatch.setattr(startup, "enabled", lambda: False)
    config = Config()
    config.data.update(game_folder=str(game_folder), user="Sam", last_sync={"at": int(time.time()) - 120, "summary": "1 upcoming raid"})
    config.token = "t"
    Syncer(config, log=lambda text: None).write_sync({"user": "A", "time": NOW, "guilds": [{"id": 1, "name": "Stone Watch", "raids": [
        {"id": 1, "title": "Molten Core", "start": int(time.time()) + 86400, "signups": []}]}]}, {})
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        root.withdraw()
        app = gargoyle_app.App(root)

        def texts(widget):
            found = []
            for child in widget.winfo_children():
                try:
                    found.append(child.cget("text"))
                except tk.TclError:
                    pass
                found += texts(child)
            return found

        shown = texts(root)
        assert "Linked as Sam" in shown and "Addon " + addon_install.installed_version(game_folder) in shown
        assert "2 minutes ago" in shown and "Nothing waiting" in shown
        assert "Molten Core" in shown and "Not signed up" in shown and "Tomorrow" in shown
        assert not app.start_hidden and app.banner.winfo_manager() == ""
        # The raid links to its signup on the website.
        opened = []
        monkeypatch.setattr(gargoyle_app.webbrowser, "open", opened.append)
        assert "Sign up on the website ›" in shown
        app.open_site("/guilds/1#raid-1")
        app.open_site("https://elsewhere.example")
        assert opened == ["https://gargoyle.gg/guilds/1#raid-1"]
        # A problem in one round of the window's loops doesn't stop them, and it's said.
        def broken():
            raise RuntimeError("boom")
        monkeypatch.setattr(app, "refresh", broken)
        app.events.put(("log", "x"))
        with pytest.raises(RuntimeError):
            app.pump()
        assert app.pump_after in root.tk.call("after", "info")
        app.report(RuntimeError, RuntimeError("boom"), None)
        assert "Something went wrong in the window (RuntimeError: boom)" in app.log_box.get("1.0", "end")
        del app.refresh  # (back to the real one)
        # Syncing needs the addon there.
        game_folder.joinpath("Interface", "AddOns", "Gargoyle", "Gargoyle.toc").rename(game_folder / "moved.toc")
        app.sync(force=True)
        assert not app.busy and "Install the Gargoyle addon first" in app.log_box.get("1.0", "end")
        game_folder.joinpath("moved.toc").rename(game_folder / "Interface" / "AddOns" / "Gargoyle" / "Gargoyle.toc")
        # A new app and a new addon: the banner, and an Update button.
        app.versions = release(addon_version="99.0", app_version="99.0")
        app.refresh()
        shown = texts(root)
        assert "Update" in shown and app.banner.winfo_manager() == "pack" and any("A new version of the Gargoyle app is out (99.0)" in t for t in shown)
    finally:
        root.destroy()




def test_a_release_only_builds_with_the_signed_addon(tmp_path, monkeypatch, release_key):
    import importlib.util
    spec = importlib.util.spec_from_file_location("build", PROJECT / "helper" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    tag = build.release_tag()
    with pytest.raises(SystemExit, match="No signed addon manifest"):
        build.check_signed(tag)
    (tmp_path / "release").mkdir()
    body = build.addon_manifest(tag)
    (tmp_path / "release" / "addon-manifest.json").write_bytes(body)
    (tmp_path / "release" / "addon-manifest.sig").write_bytes(release_key(body))
    assert build.check_signed(tag)[0] == body
    with pytest.raises(SystemExit, match="isn't the addon"):
        build.check_signed("v0.0.1-addon0.0.1")
    (tmp_path / "release" / "addon-manifest.sig").write_bytes(release_key(b"something else"))
    with pytest.raises(SystemExit, match="signature"):
        build.check_signed(tag)


def test_signatures():
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    body = signing.manifest("v1", "1.0", {"Gargoyle/A.lua": b"x"})
    good = base64.b64encode(key.sign(body))
    assert signing.verify(body, good, public)["files"] == {"Gargoyle/A.lua": hashlib_sha256(b"x")}
    assert signing.verify(body, good.decode() + "\n", public)["version"] == "1.0"
    for args in ((body + b" ", good, public), (body, good, ""), (body, b"not base64!", public), (body, good, "abc"),
                 (body, base64.b64encode(b"x" * 64), public)):
        with pytest.raises(signing.SignatureError):
            signing.verify(*args)
    odd = b'{"files": {}, "tag": "v1", "version": "1.0"}'
    with pytest.raises(signing.SignatureError, match="can't be read"):
        signing.verify(odd, base64.b64encode(key.sign(odd)), public)
    assert signing.normalized("Gargoyle/A.lua", b"a\r\nb") == b"a\nb"
    assert signing.normalized("Gargoyle/A.png", b"a\r\nb") == b"a\r\nb"


def hashlib_sha256(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()
