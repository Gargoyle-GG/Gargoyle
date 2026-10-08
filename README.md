# Gargoyle addon and app

The in-game addon and the desktop app for [Gargoyle](https://gargoyle.gg), the companion
site for WoW Forever. Free, like everything on Gargoyle.

- **The addon** (`addon/Gargoyle`) shows your guild's upcoming raids in game (and marks them on
  the game's calendar), who's signed up, and lets you sign up (Coming / Tentative / Can't come)
  without leaving WoW. Guild officers can make new raids in game. It can also keep the
  characters you pick up to date on your Gargoyle account, and follow a talent build from
  your account: the game's talent window marks the talents it still wants (talent plans).
  You still pick every talent yourself. Its Dungeons tab is a dungeon journal: every
  dungeon and raid's bosses, loot and abilities, maps, and quests with the chains that lead
  to them (its data is `Data/Journal.lua`; item and spell names and text come from the
  game), with the drops that are upgrades for your character marked, on item tooltips too.
  The website's gear planner works those out. The maps (`Media/Maps/`) are pieced together
  from the game's own minimap pictures, which are Blizzard's art. Its "Show on map" button
  sets the game's own map pin, only when you click it.
- **Damage tooltips** (`addon/Gargoyle_Tooltips`), a separate addon you can choose to install,
  add a breakdown of your spells' damage and healing to their tooltips: base numbers, your
  spell power's share, your talents, crit, and the average per cast, per second and per mana.
  Its data (`Data/<Class>.lua`) is made from the website's spell math. It's turned on or off
  in Gargoyle's options.
- **The app** (`helper/`) carries things between the game and the website, because addons
  can't go online. It also installs the addons and keeps them up to date.

**Download:** [the latest release](../../releases/latest) (`GargoyleSetup.exe`), or from
[gargoyle.gg/addon](https://gargoyle.gg/addon). Every release is built by GitHub from the code
in this repository ([how](.github/workflows/release.yml)), so what you download is exactly
what you can read here.

## What the app does and doesn't do

- It reads the Gargoyle addon's own saved file (`WTF\Account\...\SavedVariables\Gargoyle.lua`)
  after you `/reload` or log out, and sends the signups and raids you made in game and the
  characters you picked to your Gargoyle account.
- It writes your guild's raids into a small data addon (`Interface\AddOns\Gargoyle_Sync`), which
  the game loads the next time you log in or `/reload`.
- It installs and updates the Gargoyle addon (`Interface\AddOns\Gargoyle`), and Damage tooltips
  (`Interface\AddOns\Gargoyle_Tooltips`) if you ticked them, from these releases, but only if
  every file matches a manifest signed with Gargoyle's release key, which is kept offline and
  never on GitHub (see [SECURITY.md](SECURITY.md)). Unticking Damage tooltips removes that
  addon's folder again.
- When a new version of the app is out, **Update now** downloads its installer and runs it
  quietly, but only if it's the installer signed with that same release key. The installer
  closes the app, updates it and opens it again, keeping your settings.
- It never touches the running game, its memory, or any other game files, and it never plays
  for you. The addon only shows things and records your own clicks.
- It talks to `gargoyle.gg` (your raids and signups) and to GitHub (updates), nothing else.
  Your account link is a token stored encrypted with Windows' own per-user protection.
- It runs in the tray when you close its window, and only starts with Windows if you turn
  that on.

## Building it yourself

Needs Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php) on Windows.

```
python -m pip install -r requirements-build.txt
python -m pytest tests
python helper/build.py
```

The installer, the addon zip and `versions.json` end up in `dist/`. To run the app from the
code instead: `python helper/gargoyle_app.py`.

## Questions and bugs

Open an issue here. Security problems: please report them privately (see
[SECURITY.md](SECURITY.md)). Code contributions aren't accepted at the moment.

## License

All rights reserved: you're welcome to read the code and use the official releases, but not
to copy or republish it. See [LICENSE](LICENSE).
