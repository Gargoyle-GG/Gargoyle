"""Uploads a release's addons to CurseForge (run by release.yml once the release is posted).

Only the addons whose version changed since the last release go up, each to its own CurseForge
project, for WoW Forever's game version. Dungeons and Loot list Gargoyle (the core) as a
required dependency, Damage tooltips as an optional one. The Data Collector, for Gargoyle's
helpers only, isn't on CurseForge. The zips are the release's own (the same signed files the
Gargoyle app installs).

Nothing happens until the repository has both (set by its owner on GitHub):
  - the secret CURSEFORGE_API_TOKEN (a CurseForge author API token), and
  - the variable CURSEFORGE_PROJECTS: {"addon": {"id": 123, "slug": "gargoyle"}, "dungeons": {...},
    "loot": {...}, "tooltips": {...}}, each project's id and slug on CurseForge.
CURSEFORGE_GAME_VERSION (optional) is the game version's name there (default 1.60.1, WoW Forever).

    python .github/curseforge_upload.py <dist folder> [<previous release's versions.json>]
"""
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

API = "https://wow.curseforge.com/api"
TITLES = {"addon": "Gargoyle", "dungeons": "Gargoyle Dungeons", "loot": "Gargoyle Loot", "tooltips": "Gargoyle Damage Tooltips"}
NEEDS_CORE = {"dungeons": "requiredDependency", "loot": "requiredDependency", "tooltips": "optionalDependency"}


def call(path, token, body=None, content_type=None, opener=urllib.request.urlopen):
    request = urllib.request.Request(API + path, data=body, headers={"X-Api-Token": token, "User-Agent": "Gargoyle release"})
    if content_type:
        request.add_header("Content-Type", content_type)
    with opener(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8") or "null")


def game_version_id(token, name, opener=urllib.request.urlopen):
    """The id of the game version called `name` (WoW Forever's, if more than one has that name)."""
    versions = [v for v in call("/game/versions", token, opener=opener) if v.get("name") == name]
    if len(versions) > 1:
        forever = {t["id"] for t in call("/game/version-types", token, opener=opener)
                   if "forever" in (t.get("name", "") + t.get("slug", "")).lower()}
        versions = [v for v in versions if v.get("gameVersionTypeID") in forever] or versions
    if not versions:
        raise SystemExit(f"CurseForge has no game version called {name}.")
    return versions[0]["id"]


def to_upload(current, previous, projects):
    """The addons to upload: [(key, its versions.json entry)], those with a new version."""
    out = []
    for key in TITLES:
        entry = current.get(key)
        if key in projects and isinstance(entry, dict) and (previous.get(key) or {}).get("version") != entry.get("version"):
            out.append((key, entry))
    return out


def metadata(key, entry, tag, game_version, projects):
    data = {
        "changelog": f"Gargoyle release {tag}. What's new: https://gargoyle.gg/updates",
        "changelogType": "markdown", "displayName": f"{TITLES[key]} {entry['version']}",
        "gameVersions": [game_version], "releaseType": "release",
    }
    if key in NEEDS_CORE and "addon" in projects:
        data["relations"] = {"projects": [{"slug": projects["addon"]["slug"], "type": NEEDS_CORE[key]}]}
    return data


def multipart(fields, file_name, file_bytes):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
                 "Content-Type: application/zip\r\n\r\n".encode("utf-8") + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main(argv, env=os.environ, opener=urllib.request.urlopen):
    token, raw = env.get("CURSEFORGE_API_TOKEN", ""), env.get("CURSEFORGE_PROJECTS", "")
    if not token or not raw:
        print("CurseForge isn't set up for this repository: nothing uploaded.")
        return []
    projects = json.loads(raw)
    dist = Path(argv[0])
    current = json.loads((dist / "versions.json").read_text(encoding="utf-8"))
    previous = {}
    if len(argv) > 1 and Path(argv[1]).is_file():
        previous = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    uploads = to_upload(current, previous, projects)
    if not uploads:
        print("No addon has a new version: nothing uploaded to CurseForge.")
        return []
    game_version = game_version_id(token, env.get("CURSEFORGE_GAME_VERSION") or "1.60.1", opener)
    done = []
    for key, entry in uploads:
        body, content_type = multipart({"metadata": json.dumps(metadata(key, entry, current.get("tag", ""), game_version, projects))},
                                       entry["file"], (dist / entry["file"]).read_bytes())
        answer = call(f"/projects/{int(projects[key]['id'])}/upload-file", token, body, content_type, opener)
        print(f"Uploaded {TITLES[key]} {entry['version']} to CurseForge (file {answer.get('id') if isinstance(answer, dict) else '?'}).")
        done.append(key)
    return done


if __name__ == "__main__":
    main(sys.argv[1:])
