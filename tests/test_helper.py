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
import collected  # noqa: E402
import overview  # noqa: E402
import signing  # noqa: E402
import sync  # noqa: E402
import startup  # noqa: E402
import sync_file  # noqa: E402
import wow_paths  # noqa: E402
from config import Config  # noqa: E402
from version import RELEASES, SIGNED  # noqa: E402
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


def test_new_raids_from_saved_data():
    saved = {"GargoyleDB": {"newRaids": [
        {"id": "r1", "guild": 5, "title": "Molten Core" + "!" * 90, "start": 1_800_086_400, "size": 40, "notes": "N" * 1200,
         "at": 1_800_000_000, "evil": "x"},
        {"id": "r2", "guild": "5", "title": 7, "start": 1.5, "size": "forty"},  # (odd fields: the website says no)
        {"id": "bad id!", "guild": 5}, {"id": 9}, "junk"]}}
    one, two = sync_file.new_raids(saved)
    assert one == {"id": "r1", "guild": 5, "title": ("Molten Core" + "!" * 90)[:80], "start": 1_800_086_400, "size": 40,
                   "notes": "N" * 1000, "at": 1_800_000_000}
    assert two == {"id": "r2", "guild": None, "title": "", "start": None, "size": None, "notes": "", "at": None}
    assert sync_file.new_raids({"GargoyleDB": {"newRaids": "x"}}) == [] and sync_file.new_raids({}) == []
    # The data file tells the addon this app sends them.
    assert sync_file.sync_table({}, {})["can_make_raids"] is True


def test_talent_plans_in_the_data_file():
    """Each character's talents (talent plans) are copied field by field, checked and cut; the
    data file says this app sends them."""
    good = {"tree": 2, "name": "Improved Fireball", "spells": [11069, 12338], "rank": 5}
    talents = [good, {"tree": 1, "name": HOSTILE[0], "spells": list(range(1, 30)) + ["x", -5, True], "rank": 1},
               {"tree": 9, "name": "Bad tree", "rank": 1}, {"tree": 1, "name": "Bad rank", "rank": 11},
               {"tree": 1, "name": "", "rank": 1}, {"tree": True, "name": "Bool", "rank": 1}, "junk"]
    api = {"characters": [{"id": 1, "name": "Plan", "class": "mage", "talents": talents + [good] * 70},
                          {"id": 2, "name": "Old website", "class": "mage", "talents": "junk"}]}
    table = sync_file.sync_table(api, {})
    assert table["sends_talents"] is True
    plan, old = table["characters"]
    assert plan["talents"][0] == good and len(plan["talents"]) == sync_file.MAX_TALENTS
    assert plan["talents"][1] == {"tree": 1, "name": HOSTILE[0][:60], "spells": list(range(1, 11)), "rank": 1}
    assert plan["talents"][2] == good and old["talents"] == []
    # Read back in Lua: plain data.
    env = load_in_lua(sync_file.sync_lua(api, {}))
    first = env.GargoyleSync.characters[1].talents[2]
    assert first.name == HOSTILE[0][:60] and first.spells[10] == 10


def test_upgrade_picks_in_the_data_file():
    """Each character's upgrade picks (the dungeon journal) are copied row by row, checked and
    capped; the data file says this app sends them."""
    good = [[10399, 40.5, 9], [872, 12, 3.1]]
    bad = [[True, 1, 1], [0, 1, 1], [5, -1, 1], [6, 1, 5000], [7, "x", 1], ["8", 1, 1], [9, 1], "junk", [10, float("nan"), 1]]
    api = {"characters": [
        {"id": 1, "name": "Picks", "class": "mage",
         "upgrades": {"items": good + bad, "spec": HOSTILE[0] * 3, "level": 60, "stale": True, "at": 1_800_000_000}},
        {"id": 2, "name": "Many", "class": "mage", "upgrades": {"items": [[i, 1, 1] for i in range(1, 900)], "level": 99}},
        {"id": 3, "name": "None yet", "class": "mage"}, {"id": 4, "name": "Junk", "class": "mage", "upgrades": "x"}]}
    table = sync_file.sync_table(api, {})
    assert table["sends_upgrades"] is True
    picks, many, none, junk = table["characters"]
    assert picks["upgrades"] == {"items": good, "spec": (HOSTILE[0] * 3)[:40], "level": 60, "stale": True, "at": 1_800_000_000}
    assert len(many["upgrades"]["items"]) == sync_file.MAX_UPGRADES and many["upgrades"]["level"] is None
    assert "upgrades" not in none and "upgrades" not in junk
    env = load_in_lua(sync_file.sync_lua(api, {}))
    row = env.GargoyleSync.characters[1].upgrades["items"][1]
    assert (row[1], row[2], row[3]) == (10399, 40.5, 9)


def test_new_raids_are_sent_once_then_let_go(tmp_path, game_folder):
    calls = []

    class Answer:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class Http:
        def request(self, method, url, headers=None, timeout=None, json=None):
            calls.append((url.rsplit("/", 1)[1], json))
            if url.endswith("/api/app/raids"):
                return Answer({"results": [{"id": r["id"], "result": "saved", "raid": 77} for r in json["raids"]]})
            if url.endswith("/api/app/signups"):
                return Answer({"results": [{"id": a["id"], "result": "saved"} for a in json["actions"]]})
            return Answer({"user": "A", "time": 1, "guilds": [{"id": 5, "name": "G", "raids": [
                {"id": 77, "title": "Onyxia", "start": 1_900_000_000, "signups": []}]}]})

    saved = game_folder / "WTF" / "Account" / "123#1" / "SavedVariables" / "Gargoyle.lua"
    saved.write_text('GargoyleDB = { ["newRaids"] = { { ["id"] = "r1", ["guild"] = 5, ["title"] = "Onyxia", '
                     '["start"] = 1900000000, ["at"] = 1800000000 } } }')
    config = Config(tmp_path / "config.json")
    config.data.update(site="https://gargoyle.gg", game_folder=str(game_folder))
    config.token = "t"
    syncer = Syncer(config, http=Http(), log=lambda text: None)
    assert syncer.run() == "1 upcoming raid, 1 new raid sent"
    assert [c[0] for c in calls] == ["raids", "sync"] and calls[0][1]["raids"][0]["title"] == "Onyxia"
    assert syncer.table["done"] == {"r1": "saved"}  # (so the addon lets it go)
    # The window: it's waiting until the website has answered, then it's the website's raid.
    assert overview.raids(syncer.table, [], {}, 1_800_000_000, syncer.new_raids)[0]["made"]
    assert [r.get("made") for r in overview.raids(syncer.table, [], config.get("sent"), 1_800_000_000, syncer.new_raids)] == [None]
    calls.clear()
    syncer.run()
    assert [c[0] for c in calls] == ["sync"]  # not sent twice


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
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
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


def test_a_broken_link_or_an_update_cut_short_is_put_right(tmp_path):
    """A link to a folder that's gone: "not installed", and in the way of installing, until
    Install removes the link (only the link). An update cut short between moving the old copy
    aside and putting the new one in: the old copy goes back."""
    import os
    import shutil
    _winapi = pytest.importorskip("_winapi")
    game = tmp_path / "_classic_"
    addons = game / "Interface" / "AddOns"
    addons.mkdir(parents=True)
    source = tmp_path / "repo" / "Gargoyle"
    source.mkdir(parents=True)
    (source / "Gargoyle.toc").write_text("## Version: 0.1.0\n")
    _winapi.CreateJunction(str(source), str(addons / "Gargoyle"))
    assert not addon_install.is_dead_link(addons / "Gargoyle")
    shutil.rmtree(tmp_path / "repo")
    assert addon_install.is_dead_link(addons / "Gargoyle") and addon_install.installed_version(game) is None
    assert addon_install.repair(game, links=False) is None and os.path.lexists(addons / "Gargoyle")  # (waits for a click)
    data = addon_zip(version="1.0.0")
    assert addon_install.install(game, data, signed_for(data, "1.0.0")) == "1.0.0"
    assert not addon_install.is_linked(addons / "Gargoyle")
    # Cut short: the old copy aside, a half-made new one, no addon.
    os.replace(addons / "Gargoyle", addons / "Gargoyle.old")
    (addons / "Gargoyle.new").mkdir()
    assert addon_install.installed_version(game) is None
    assert addon_install.repair(game, links=False) == "put back the copy an update cut short had moved aside"
    assert addon_install.installed_version(game) == "1.0.0"
    assert addon_install.repair(game) is None  # (nothing more to put right)
    newer = addon_zip(version="1.1.0")
    assert addon_install.install(game, newer, signed_for(newer, "1.1.0")) == "1.1.0"
    assert sorted(p.name for p in addons.iterdir()) == ["Gargoyle"]


def test_the_app_installer_is_signed_after_the_build(release_key):
    import base64
    import version
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = version.ADDON_SIGNING_KEY
    app = offer_for(b"setup", "9.1.0", "GargoyleSetup.exe")
    body = signing.app_manifest("v9.1.0-addon9.0.0", app)
    assert signing.verify_app(body, release_key(body), key) == {"kind": "app", "tag": "v9.1.0-addon9.0.0", **app}
    # An addon's manifest isn't an installer's, nor the other way round.
    addon_body = signing.manifest("v9.1.0-addon9.0.0", "9.0.0", {"Gargoyle/Gargoyle.toc": b"x"})
    with pytest.raises(signing.SignatureError):
        signing.verify_app(addon_body, release_key(addon_body), key)
    with pytest.raises(signing.SignatureError):
        signing.verify(body, release_key(body), key)
    # Changed after signing, or signed by another key: no.
    other = base64.b64encode(Ed25519PrivateKey.generate().sign(body))
    for bad, signature in ((body.replace(b'"9.1.0"', b'"9.2.0"'), release_key(body)), (body, other), (body, b"")):
        with pytest.raises(signing.SignatureError):
            signing.verify_app(bad, signature, key)


def test_update_now_runs_only_the_signed_installer(tmp_path, release_key):
    pytest.importorskip("tkinter")
    import json
    import queue
    import types
    import gargoyle_app
    import self_update
    setup = b"MZ the new installer"
    versions = release(app=setup, app_version="99.0.0")
    app = addon_install.app_installer(versions)
    assert self_update.installer(versions, "1.0.0") == app and self_update.installer(versions, "99.0.0") is None
    body = signing.app_manifest(versions["tag"], versions["app"])
    files = {"versions.json": json.dumps(versions).encode(), "GargoyleSetup.exe": setup,
             "app-manifest.json": body, "app-manifest.sig": release_key(body)}
    config = Config(tmp_path / "config.json")
    launched = []

    def window(changed=None):
        w = types.SimpleNamespace(events=queue.Queue(), config=config, versions=versions, app_offer=None,
                                  update_busy=True, updating=None, next_version_check=time.time() + 6 * 3600)
        w.retry_app_soon = lambda: gargoyle_app.App.retry_app_soon(w)
        w.syncer = Syncer(config, http=FakeGitHub({**files, **(changed or {})}), log=lambda text: None)
        gargoyle_app.App._check_app(w)
        return w

    def update(w):
        gargoyle_app.App._update_app(w, app, temp=tmp_path, launch=lambda args, **kw: launched.append(args))

    # Signed: Update now downloads it, checks it and starts it quietly. Earlier ones are cleared.
    (tmp_path / "GargoyleUpdate").mkdir()
    (tmp_path / "GargoyleUpdate" / "GargoyleSetup-1.0.0.exe").write_bytes(b"old")
    w = window()
    assert w.app_offer == app
    update(w)
    (args,) = launched
    assert args[1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/fromapp=1"]
    assert args[0] == str(tmp_path / "GargoyleUpdate" / "GargoyleSetup-99.0.0.exe")
    assert Path(args[0]).read_bytes() == setup and not (tmp_path / "GargoyleUpdate" / "GargoyleSetup-1.0.0.exe").exists()
    assert "Installing Gargoyle 99.0.0" in w.updating and w.update_busy
    # Not signed (yet), signed by another key, or signed for another installer: the download
    # button instead.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    another = signing.app_manifest(versions["tag"], {**versions["app"], "sha256": "0" * 64})
    for changed in ({"app-manifest.json": None}, {"app-manifest.sig": b"junk"},
                    {"app-manifest.sig": base64.b64encode(Ed25519PrivateKey.generate().sign(body))},
                    {"app-manifest.json": another, "app-manifest.sig": release_key(another)}):
        w = window(changed)
        assert w.app_offer is None  # (None: not there)
        assert w.next_version_check <= time.time() + gargoyle_app.UNSIGNED_RETRY_SECONDS  # (asked again in minutes)
        # ...for an hour at most: a release that's never signed waits for the usual checks.
        for _ in range(gargoyle_app.UNSIGNED_RETRIES + 2):
            w.next_version_check = time.time() + 6 * 3600
            gargoyle_app.App._check_app(w)
        assert w.next_version_check > time.time() + 3600 and w.quick_retries == gargoyle_app.UNSIGNED_RETRIES
    # Swapped on GitHub after it was signed: downloaded, refused, never run.
    w = window({"GargoyleSetup.exe": b"MZ something else"})
    assert w.app_offer == app
    update(w)
    assert len(launched) == 1 and not w.update_busy and w.app_offer is None and "didn't work" in w.updating
    assert w.next_version_check <= time.time() + gargoyle_app.UNSIGNED_RETRY_SECONDS
    # The release's own signed copy is asked for first, then the public repo's.
    asked = [url for url, _ in window({"app-manifest.json": None}).syncer.http.asked if "app-manifest.json" in url]
    assert asked == [f"{RELEASES}/download/{versions['tag']}/app-manifest.json", f"{SIGNED}/app-manifest.json"]


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
    assert addon_install.offer(good) == {**good["addon"], "tag": "v9.1.0-addon9.0.0", "key": "addon", "name": "Gargoyle",
                                         "url": f"{RELEASES}/download/v9.1.0-addon9.0.0/Gargoyle-addon.zip"}
    # Damage tooltips: its own entry (not there in releases before it).
    tips = offer_for(b"tips", "1.0.0", "Gargoyle_Tooltips-addon.zip")
    assert addon_install.offer({**good, "tooltips": tips}, "tooltips") == {
        **tips, "tag": "v9.1.0-addon9.0.0", "key": "tooltips", "name": "Gargoyle_Tooltips",
        "url": f"{RELEASES}/download/v9.1.0-addon9.0.0/Gargoyle_Tooltips-addon.zip"}
    assert addon_install.offer(good, "tooltips") is None and addon_install.offer({**good, "app": tips}, "app") is None
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
        name = url.split("?")[0].rsplit("/", 1)[1]
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


def test_the_addon_fits_what_every_app_will_install():
    """The addon (with its dungeon maps) stays well inside the download, unpacked size and file
    limits, which apps already out there check too (1.5.0's are the same)."""
    import io
    import zipfile
    data = addon_zip()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        unpacked, count = sum(i.file_size for i in z.infolist()), len(z.infolist())
    assert len(data) < 0.8 * addon_install.MAX_DOWNLOAD, len(data)
    assert unpacked < 0.85 * addon_install.MAX_UNPACKED, unpacked
    assert count < 0.5 * addon_install.MAX_FILES, count


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
    assert tag == (f"v{build.app_version()}-addon{build.addon_version()}-tips{build.addon_version('tooltips')}"
                   f"-col{build.addon_version('collector')}")
    # Damage tooltips: their own zip, unpacking as Gargoyle_Tooltips/...
    tips = build.build_addon(tmp_path / "a", "tooltips")
    with zipfile.ZipFile(tips) as z:
        names = z.namelist()
        assert "Gargoyle_Tooltips/Gargoyle_Tooltips.toc" in names and "Gargoyle_Tooltips/Data/Mage.lua" in names
        assert all(n.startswith("Gargoyle_Tooltips/") for n in names)
        assert json.loads(build.addon_manifest("t", "tooltips"))["files"] == {
            n: hashlib.sha256(z.read(n)).hexdigest() for n in names}
    # The Data Collector: likewise, as Gargoyle_Collector/...
    with zipfile.ZipFile(build.build_addon(tmp_path / "a", "collector")) as z:
        names = z.namelist()
        assert "Gargoyle_Collector/Gargoyle_Collector.toc" in names and "Gargoyle_Collector/Collector.lua" in names
        assert all(n.startswith("Gargoyle_Collector/") for n in names)


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
    # Raids made in game and not sent yet are listed too (with nothing to link to yet).
    made = [{"id": "r1", "guild": 1, "title": "Onyxia", "start": NOW + 3600, "size": None},
            {"id": "r2", "guild": 9, "title": "", "start": NOW + 3 * 86400, "size": 40},
            {"id": "r3", "guild": 1, "title": "Sent", "start": NOW + 7200, "size": None}]
    raids = overview.raids(sample_table(), [], {"r3": {"result": "saved"}}, NOW, made)
    assert [r["title"] for r in raids] == ["Onyxia", "Molten Core", "Zul'Gurub", "Raid", "Blackwing Lair"]
    ony = raids[0]
    assert ony["made"] and ony["guild"] == "Stone Watch" and overview.signup_text(ony) == "New raid"
    assert overview.raid_path(ony) is None and raids[3]["guild"] == ""


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
        # Its installer not signed (yet), or run from the source code: the download. Signed, in
        # the installed app: Update now.
        assert app.download_button.winfo_manager() == "pack" and app.update_button.winfo_manager() == ""
        app.app_offer = addon_install.app_installer(app.versions)
        app.refresh()
        assert app.download_button.winfo_manager() == "pack"
        monkeypatch.setattr(gargoyle_app, "installed_app", lambda: True)
        app.refresh()
        assert app.update_button.winfo_manager() == "pack" and app.download_button.winfo_manager() == ""
        # The Data Collector: a helper code to unlock it, then Send (helpers only).
        assert app.unlock_button.winfo_manager() == "pack" and app.send_button.winfo_manager() == ""
        assert any("Type the helper code you were given" in t for t in texts(root))
        app.config.set("helper", True)
        app.collector_counts = {"items": 12, "spells": 3, "talents": 1, "trainers": 0}
        app.refresh()
        assert app.unlock_button.winfo_manager() == "" and app.send_button.winfo_manager() == "pack"
        assert any("Waiting to send: 12 items, 3 spells and a talent tree." in t for t in texts(root))
        # No longer a helper: the collector comes out of the game.
        collector_folder = game_folder / "Interface" / "AddOns" / "Gargoyle_Collector"
        collector_folder.mkdir()
        (collector_folder / "Gargoyle_Collector.toc").write_text("## Version: 1.0.0\n")
        app.config.set("helper", False)
        app.events.put(("collector", False))
        app.pump()
        assert not collector_folder.exists() and "Removed the Data Collector addon" in app.log_box.get("1.0", "end")
    finally:
        root.destroy()




def test_githubs_release_build_takes_this_releases_tag():
    """The release workflow refuses tags it doesn't recognise: this release's must be one it does."""
    here = PROJECT / "public" / ".github" / "workflows" / "release.yml"  # (in the public repo it's at the top)
    workflow = (here if here.exists() else PROJECT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    pattern = re.search(r"-notmatch '([^']+)'", workflow).group(1)
    import importlib.util
    spec = importlib.util.spec_from_file_location("build", PROJECT / "helper" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert re.match(pattern, build.release_tag()), build.release_tag()


def test_a_release_only_builds_with_the_signed_addon(tmp_path, monkeypatch, release_key):
    import importlib.util
    spec = importlib.util.spec_from_file_location("build", PROJECT / "helper" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    tag = build.release_tag()
    with pytest.raises(SystemExit, match="No signed addon-manifest.json"):
        build.check_signed(tag)
    (tmp_path / "release").mkdir()
    body = build.addon_manifest(tag)
    (tmp_path / "release" / "addon-manifest.json").write_bytes(body)
    (tmp_path / "release" / "addon-manifest.sig").write_bytes(release_key(body))
    with pytest.raises(SystemExit, match="No signed tooltips-manifest.json"):  # (every addon is signed)
        build.check_signed(tag)
    tips = build.addon_manifest(tag, "tooltips")
    (tmp_path / "release" / "tooltips-manifest.json").write_bytes(tips)
    (tmp_path / "release" / "tooltips-manifest.sig").write_bytes(release_key(tips))
    with pytest.raises(SystemExit, match="No signed collector-manifest.json"):
        build.check_signed(tag)
    collector = build.addon_manifest(tag, "collector")
    (tmp_path / "release" / "collector-manifest.json").write_bytes(collector)
    (tmp_path / "release" / "collector-manifest.sig").write_bytes(release_key(collector))
    signed = build.check_signed(tag)
    assert signed["addon"][0] == body and signed["tooltips"][0] == tips and signed["collector"][0] == collector
    # Each manifest is its own addon's: swapping them doesn't pass.
    (tmp_path / "release" / "tooltips-manifest.json").write_bytes(body)
    (tmp_path / "release" / "tooltips-manifest.sig").write_bytes(release_key(body))
    with pytest.raises(SystemExit, match="isn't the Gargoyle_Tooltips addon"):
        build.check_signed(tag)
    (tmp_path / "release" / "tooltips-manifest.json").write_bytes(tips)
    (tmp_path / "release" / "tooltips-manifest.sig").write_bytes(release_key(tips))
    # A checkout with Windows line endings still passes (git may convert them).
    (tmp_path / "release" / "addon-manifest.json").write_bytes(body.replace(b"\n", b"\r\n"))
    assert build.check_signed(tag)["addon"][0] == body
    (tmp_path / "release" / "addon-manifest.json").write_bytes(body)
    with pytest.raises(SystemExit, match="isn't the Gargoyle addon"):
        build.check_signed("v0.0.1-addon0.0.1-tips0.0.1-col0.0.1")
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


# ---- Damage tooltips: a second addon, installed when ticked ----

def tips_zip(version=None):
    """Gargoyle Damage Tooltips zipped like helper/build.py does."""
    import io
    import zipfile
    folder = PROJECT / "addon" / "Gargoyle_Tooltips"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                text = path.read_bytes()
                if version and path.name == "Gargoyle_Tooltips.toc":
                    text = re.sub(rb"## Version: \S+", b"## Version: " + version.encode(), text)
                z.writestr("Gargoyle_Tooltips/" + path.relative_to(folder).as_posix(), text)
    return buffer.getvalue()


def test_installing_and_removing_damage_tooltips(tmp_path, game_folder):
    tips = tips_zip(version="1.0.0")
    addons = game_folder / "Interface" / "AddOns"
    assert addon_install.installed_version(game_folder, addon_install.TOOLTIPS) is None
    assert addon_install.install(game_folder, tips, signed_for(tips, "1.0.0"), addon_install.TOOLTIPS) == "1.0.0"
    assert (addons / "Gargoyle_Tooltips" / "Data" / "Mage.lua").is_file() and (addons / "Gargoyle" / "Gargoyle.toc").is_file()
    # Each addon's zip only goes in its own folder, and only Gargoyle's addons are installed.
    gargoyle = addon_zip()
    for data, name in ((gargoyle, addon_install.TOOLTIPS), (tips, addon_install.NAME), (tips, "Other")):
        with pytest.raises(addon_install.InstallError):
            addon_install.install(game_folder, data, signed_for(data), name)
    # Unticked: the folder goes; Gargoyle's own can't be removed this way.
    assert addon_install.uninstall(game_folder, addon_install.TOOLTIPS) is True
    assert not (addons / "Gargoyle_Tooltips").exists() and not (addons / "Gargoyle_Tooltips.old").exists()
    assert addon_install.uninstall(game_folder, addon_install.TOOLTIPS) is False
    with pytest.raises(addon_install.InstallError):
        addon_install.uninstall(game_folder, addon_install.NAME)
    assert (addons / "Gargoyle" / "Gargoyle.toc").is_file()


def test_the_installers_tooltips_tick(tmp_path):
    assert addon_install.installer_choice(tmp_path) is None
    (tmp_path / "choices.ini").write_text("[addons]\ntooltips=1\n")
    assert addon_install.installer_choice(tmp_path) is True and not (tmp_path / "choices.ini").exists()
    (tmp_path / "choices.ini").write_bytes("[addons]\r\ntooltips=0\r\n".encode("utf-16"))
    assert addon_install.installer_choice(tmp_path) is False
    (tmp_path / "choices.ini").write_text("[addons]\ntooltips=maybe\n")
    assert addon_install.installer_choice(tmp_path) is None and not (tmp_path / "choices.ini").exists()


def test_the_app_installs_ticked_damage_tooltips(tmp_path, game_folder, release_key):
    pytest.importorskip("tkinter")
    import json
    import queue
    import types
    import gargoyle_app
    installed = addon_install.installed_version(game_folder)
    tag = "v9.1.0-addon9.0.0-tips1.0.0"

    def github(tips_version):
        tips = tips_zip(version=tips_version)
        body = signing.manifest(tag, tips_version, {n: d for n, d in zip_files(tips).items()})
        versions = {**release(addon_version=installed, tag=tag),
                    "tooltips": offer_for(tips, tips_version, "Gargoyle_Tooltips-addon.zip")}
        return FakeGitHub({"versions.json": json.dumps(versions).encode(), "Gargoyle_Tooltips-addon.zip": tips,
                           "tooltips-manifest.json": body, "tooltips-manifest.sig": release_key(body)})

    config = Config(tmp_path / "config.json")
    config.data.update(game_folder=str(game_folder))
    app = types.SimpleNamespace(events=queue.Queue(), config=config, checking=True, next_version_check=0, versions={},
                                app_offer=None)
    app._update_addon = lambda *args: gargoyle_app.App._update_addon(app, *args)
    app._check_app = lambda: gargoyle_app.App._check_app(app)
    app.retry_app_soon = lambda: gargoyle_app.App.retry_app_soon(app)

    def check(tips_version, install=False):
        app.syncer = Syncer(config, http=github(tips_version), log=lambda text: None)
        gargoyle_app.App._check_versions(app, install)
        said = []
        while not app.events.empty():
            event = app.events.get()
            said += [event[1]] if event[0] == "log" else []
        return " ".join(said), addon_install.installed_version(game_folder, addon_install.TOOLTIPS)

    assert check("1.0.0") == ("", None)  # (not ticked)
    config.set("tooltips", True)
    said, version = check("1.0.0")
    assert version == "1.0.0" and "Installed the Damage tooltips addon 1.0.0." in said
    config.set("auto_update", False)
    assert check("1.1.0")[1] == "1.0.0"  # (updates switched off: waits for a click)
    said, version = check("1.1.0", install=True)
    assert version == "1.1.0" and "Updated the Damage tooltips addon to 1.1.0." in said


def zip_files(data):
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}


# ---- The Data Collector (helpers only, sent when asked) ----

def test_collected_data_from_saved_files():
    saved = {"GargoyleCollectorDB": {"v": 1, "id": "ab12", "items": {5: {"name": "Axe", "seen": 9, "build": 3}, "x": {"name": "?"},
                                                                       6: {"name": "No time"}, 7: "junk"},
                                     "talents": {"MAGE": {"nodes": [], "seen": 10}, "mage": {"seen": 10}},
                                     "spells": [{"name": "Listed", "seen": 11}]}}
    file_id, found = collected.entries(saved)
    assert file_id == "ab12"
    assert [(e["kind"], e["key"], e["seen"], e["build"], e["data"]) for e in found] == [
        ("items", 5, 9, 3, {"name": "Axe"}), ("spells", 1, 11, None, {"name": "Listed"}), ("talents", "MAGE", 10, None, {"nodes": []})]
    assert collected.entries({"GargoyleCollectorDB": {"v": 2, "id": "ab"}}) == (None, [])
    assert collected.entries({"GargoyleCollectorDB": {"v": 1, "id": "../x"}}) == (None, [])
    assert [e["key"] for e in collected.waiting((file_id, found), {"ab12": 10})] == [1]
    assert collected.describe(collected.counts(found)) == "1 item, 1 spell and a talent tree"
    assert collected.describe({"items": 1200, "trainers": 2}) == "1,200 items and 2 spells"
    assert collected.describe({}) == "nothing"
    big = [{"kind": "items", "key": i, "build": 1, "seen": 1, "data": {"name": "x" * 1000}} for i in range(1, 400)]
    sizes = [len(b) for b in collected.batches(big)]
    assert sum(sizes) == 399 and max(sizes) < 400 and len(sizes) > 2
    assert all(len(__import__("json").dumps(b)) < 200 * 1024 for b in collected.batches(big))
    assert list(collected.batches([{"kind": "items", "key": 1, "build": 1, "seen": 1, "data": {"x": "y" * 300000}}])) == []


def test_a_helper_sends_what_the_collector_noted_and_it_clears(tmp_path, game_folder):
    """The whole trip: the collector addon notes things in game, the game saves them, the
    helper clicks Send, the website gets them, and the addon clears them at the next login."""
    from test_addon import NOW, collector as collector_game, settle
    game = collector_game()
    settle(game)
    game.lua.execute(SERIALIZE)
    saved_text = "GargoyleCollectorDB = " + game.lua.eval("serialize(GargoyleCollectorDB)") + "\n"
    file_id = game.lua.eval("GargoyleCollectorDB.id")
    (game_folder / "WTF" / "Account" / "123#1" / "SavedVariables" / "Gargoyle_Collector.lua").write_text(saved_text)
    calls, helper = [], {"on": False}

    class Answer:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class Http:
        def request(self, method, url, headers=None, timeout=None, json=None):
            calls.append((url.rsplit("/", 1)[1], json))
            if url.endswith("/api/app/collected"):
                return Answer({"saved": len(json["entries"]), "known": 0, "skipped": 0})
            return Answer({"user": "A", "time": 1, "guilds": [], "helper": helper["on"]})

    config = Config(tmp_path / "config.json")
    config.data.update(site="https://gargoyle.gg", game_folder=str(game_folder))
    config.token = "t"
    syncer = Syncer(config, http=Http(), log=lambda text: None)
    syncer.run()
    with pytest.raises(ValueError, match="isn't a helper"):  # (only helpers send, and only when asked)
        syncer.send_collected()
    assert [c[0] for c in calls] == ["sync"]
    helper["on"] = True
    syncer.run()
    assert config.get("helper") is True and [c[0] for c in calls] == ["sync", "sync"]  # (a sync sends none of it)
    assert syncer.collected_waiting() == {"items": 3, "spells": 6, "talents": 1, "trainers": 0}
    assert syncer.send_collected() == "Sent 10 entries: 10 new to the website, 0 it had already."
    sent = [e for name, body in calls if name == "collected" for e in body["entries"]]
    assert sorted({e["kind"] for e in sent}) == ["items", "spells", "talents"] and len(sent) == 10
    assert all(set(e) == {"kind", "key", "build", "data"} and "seen" not in e["data"] for e in sent)
    assert config.get("collected") == {file_id: NOW}
    assert syncer.collected_waiting() == {"items": 0, "spells": 0, "talents": 0, "trainers": 0}
    assert syncer.send_collected() == "Nothing new to send."
    # The next sync tells the addon, which clears what was sent at the next login.
    syncer.run()
    data = (game_folder / "Interface" / "AddOns" / "Gargoyle_Sync" / "Data.lua").read_text(encoding="utf-8")
    assert load_in_lua(data).GargoyleSync.collected[file_id] == NOW
    game = collector_game(saved=saved_text + data, now=NOW + 300)
    settle(game)
    db = game.lua.globals().GargoyleCollectorDB
    assert list(db["items"].keys()) == [] and list(db.spells.keys()) == [] and db.talents.MAGE is None


def test_a_helper_code_in_the_app(tmp_path, game_folder):
    class Answer:
        def __init__(self, status, data):
            self.status_code, self.data = status, data

        def json(self):
            return self.data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)

    answers = []

    class Http:
        def request(self, method, url, headers=None, timeout=None, json=None):
            assert url.endswith("/api/app/collector/unlock") and headers["Authorization"] == "Bearer t"
            return answers.pop(0)

    config = Config(tmp_path / "config.json")
    config.data.update(site="https://gargoyle.gg", game_folder=str(game_folder))
    config.token = "t"
    syncer = Syncer(config, http=Http(), log=lambda text: None)
    answers.append(Answer(400, {"helper": False, "error": "That helper code didn't work."}))
    with pytest.raises(ValueError, match="That helper code didn't work"):
        syncer.unlock_collector("AAAA-BBBB-CCCC")
    answers.append(Answer(429, {}))
    with pytest.raises(ValueError, match="too many tries"):
        syncer.unlock_collector("AAAA-BBBB-CCCC")
    assert config.get("helper") is None
    answers.append(Answer(200, {"helper": True}))
    assert syncer.unlock_collector("abcd efgh jkmn") is True and config.get("helper") is True


def test_installing_and_removing_the_data_collector(tmp_path, game_folder):
    import io
    import zipfile
    folder = PROJECT / "addon" / "Gargoyle_Collector"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.writestr("Gargoyle_Collector/" + path.relative_to(folder).as_posix(), path.read_bytes())
    data = buffer.getvalue()
    addons = game_folder / "Interface" / "AddOns"
    version = addon_install.install(game_folder, data, signed_for(data, "1.0.0"), addon_install.COLLECTOR)
    assert version == addon_install.installed_version(game_folder, addon_install.COLLECTOR)
    assert (addons / "Gargoyle_Collector" / "Collector.lua").is_file()
    assert addon_install.offer({"tag": "t1", "collector": offer_for(data, "1.0.0", "Gargoyle_Collector-addon.zip")},
                               "collector")["name"] == "Gargoyle_Collector"
    assert addon_install.uninstall(game_folder, addon_install.COLLECTOR) is True
    assert not (addons / "Gargoyle_Collector").exists() and (addons / "Gargoyle" / "Gargoyle.toc").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="the app's one-copy check is Windows' own")
def test_a_stuck_copy_of_the_app_doesnt_stop_it_opening(tmp_path, monkeypatch):
    import threading

    import gargoyle_app
    monkeypatch.setattr(gargoyle_app, "config_folder", lambda: tmp_path)
    gargoyle_app.already_running(wait=0.3)  # (holds the one-copy mark, so every check below finds a copy running)
    note = tmp_path / gargoyle_app.SHOW_FILE

    # A copy that answers is asked to show itself, and this one stops.
    answer = threading.Timer(0.1, lambda: note.unlink())
    answer.start()
    assert gargoyle_app.already_running(wait=2) is True
    answer.join()

    # One that doesn't answer is stuck: the packaged app closes it (never itself) and starts.
    ran = []
    monkeypatch.setattr(gargoyle_app.subprocess, "run", lambda args, **kw: ran.append(args))
    monkeypatch.setattr(gargoyle_app.time, "sleep", lambda s: None)
    monkeypatch.setattr(gargoyle_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gargoyle_app.sys, "executable", r"C:\Programs\Gargoyle\GargoyleApp.exe")
    (tmp_path / gargoyle_app.QUIT_FILE).write_text("quit")
    assert gargoyle_app.already_running(wait=0.3) is False
    assert ran == [["taskkill", "/F", "/IM", "GargoyleApp.exe", "/FI", f"PID ne {gargoyle_app.os.getpid()}"]]
    assert not note.exists() and not (tmp_path / gargoyle_app.QUIT_FILE).exists()

    # From source (the program is Python itself) nothing is closed: it says a copy is running.
    monkeypatch.setattr(gargoyle_app.sys, "frozen", False)
    assert gargoyle_app.already_running(wait=0.3) is True and len(ran) == 1


def test_update_checks_can_be_switched_off(tmp_path, monkeypatch):
    pytest.importorskip("tkinter")
    import types
    import gargoyle_app
    started = []
    monkeypatch.setattr(gargoyle_app.threading, "Thread", lambda target, args, daemon: types.SimpleNamespace(
        start=lambda: started.append(args)))
    config = Config(tmp_path / "config.json")
    app = types.SimpleNamespace(config=config, checking=False, _check_versions=None)
    gargoyle_app.App.check_versions(app)
    assert started == [(False,)]  # (on unless switched off)
    config.set("update_checks", False)
    app.checking = False
    gargoyle_app.App.check_versions(app)
    assert started == [(False,)]  # off: GitHub isn't asked on its own...
    gargoyle_app.App.check_versions(app, install=True)
    assert started == [(False,), (True,)]  # ...only when you click to install
