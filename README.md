# Gargoyle addon and app

The in-game addon and the desktop app for [Gargoyle](https://gargoyle.gg), the companion
site for WoW Forever. Free, like everything on Gargoyle.

- **The addon** (`addon/Gargoyle`) shows your guild's upcoming raids in game (and marks them on
  the game's calendar), who's signed up, and lets you sign up (Coming / Tentative / Can't come)
  without leaving WoW. Guild officers can make new raids in game. It can also keep the
  characters you pick up to date on your Gargoyle account, and follow a talent build from
  your account: the game's talent window marks the talents it still wants (talent plans).
  You still pick every talent yourself. Its Dungeons tab is a dungeon journal: every
  dungeon and raid's bosses, loot and abilities, and quests with the chains that lead
  to them (its data is `Data/Journal.lua`; item and spell names and text come from the
  game), with the drops that are upgrades for your character marked, on item tooltips too.
  The website's gear planner works those out. Its "Show on map" button
  sets the game's own map pin, only when you click it.
- **Damage tooltips** (`addon/Gargoyle_Tooltips`), a separate addon you can choose to install,
  add a breakdown of your spells' damage and healing to their tooltips: base numbers, your
  spell power's share, your talents, crit, and the average per cast, per second and per mana.
  Its data (`Data/<Class>.lua`) is made from the website's spell math. It's turned on or off
  in Gargoyle's options.
- **The Data Collector** (`addon/Gargoyle_Collector`), only for Gargoyle's helpers, notes what
  the game shows you about items, spells, talents and trainers, so gargoyle.gg's game data
  stays up to date. It only reads things you come across (it never runs through item or spell
  numbers), a few at a time and never in combat, and notes nothing about you or other players
  but your class. It's installed by the app once a helper types their helper code, and nothing
  is sent until they click **Send collected data**. It's turned on or off in Gargoyle's options.
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
  addon's folder again. For helpers, it installs the Data Collector
  (`Interface\AddOns\Gargoyle_Collector`) the same way, and removes it if their helper code is
  revoked.
- For helpers, **Send collected data** reads the Data Collector's saved file
  (`SavedVariables\Gargoyle_Collector.lua`) and sends what it noted to gargoyle.gg. Only then:
  never on its own.
- When a new version of the app is out, **Update now** downloads its installer and runs it
  quietly, but only if it's the installer signed with that same release key. The installer
  closes the app, updates it and opens it again, keeping your settings.
- It never touches the running game, its memory, or any other game files, and it never plays
  for you. The addon only shows things and records your own clicks.
- It talks to `gargoyle.gg` (your raids and signups) and to GitHub (updates), nothing else.
  The update checks can be switched off in its Settings. Your account link is a token stored
  encrypted with Windows' own per-user protection.
- It runs in the tray when you close its window, and only starts with Windows if you turn
  that on.

## Uninstalling

Windows' **Settings > Apps** (or Control Panel's Programs and Features): pick **Gargoyle** and
Uninstall. It asks whether to also remove the app's settings (`%APPDATA%\Gargoyle`). The addons
are folders in the game's `Interface\AddOns` (`Gargoyle`, `Gargoyle_Tooltips`,
`Gargoyle_Collector` and `Gargoyle_Sync`): delete them to remove them from the game.

## Privacy

The app sends only what's described above, only to gargoyle.gg (once you link it to your
account) and to GitHub (to check for and download updates, which you can switch off in its
Settings). The installer shows this before it installs. The full privacy policy is at
[gargoyle.gg/privacy](https://gargoyle.gg/privacy); GitHub's own is
[here](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement).
The addons themselves never go online: games don't let addons do that.

## Code signing policy

Windows releases (`GargoyleSetup.exe` and the app inside it) are to be signed through the
SignPath Foundation, once it accepts the project: free code signing provided by
[SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).
Until then they're unsigned (the addons and app updates are always checked with Gargoyle's own
release key, as above).

- Only releases built by this repository's [release workflow](.github/workflows/release.yml),
  from a tagged version of this code, are signed. Nothing built elsewhere is.
- Committers, reviewers and approvers: the members of the
  [Gargoyle-GG organization](https://github.com/orgs/Gargoyle-GG/people). Each release is
  approved by hand before it's signed. Code contributions aren't accepted at the moment;
  if they are later, every change from outside the team is reviewed first.
- Privacy: see [Privacy](#privacy) above.

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

Copyright (C) 2026 Gargoyle.

Free software under the [GNU General Public License, version 3](LICENSE): you may use, study,
share and change it, and copies or changed versions you pass on must be under the same license,
with their source code. It comes with no warranty.

Only releases from this repository (or [gargoyle.gg/addon](https://gargoyle.gg/addon)) are
official. Other copies can't install updates signed with Gargoyle's release key, and the
official app won't install anything else.
