"""The Gargoyle app's window: link your account, and leave it running (in the tray) while
you play. It syncs whenever the game saves (on /reload or logout) and every few minutes,
installs and updates the Gargoyle addon, and shows what's synced: your upcoming raids,
signups still to send and the characters picked in game.

The work happens elsewhere: sync.py (syncing), addon_install.py (the addon), overview.py
(what's shown), startup.py (starting with Windows). This is just the window around them.

Run from source:  python helper/gargoyle_app.py  (packaged as GargoyleApp.exe by
helper/build.py). --tray starts it in the tray, as starting with Windows does.
"""
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import requests

import addon_install
import overview
import signing
import startup
import wow_paths
from config import Config, folder as config_folder
from sync import Syncer, Unlinked, safe_site
from version import APP_VERSION, RELEASES

TICK_MS = 5000
PUMP_MS = 250
VERSION_CHECK_SECONDS = 6 * 3600  # how often it asks whether the addon or app has a new version
VERSION_RETRY_SECONDS = 600  # (sooner after a check that didn't get through, e.g. starting with Windows before the internet is up)
SHOW_FILE = "show"  # left in the settings folder by a second copy of the app: "show the window"
QUIT_FILE = "quit"  # left there by the installer before it updates or removes the app

# gargoyle.gg's colours (static/css)
BG, PANEL, INSET = "#0f0c09", "#1a1510", "#0b0907"
BORDER, BORDER_STRONG, RAISED = "#3a2f22", "#5a4832", "#2a2118"
GOLD, GOLD_LIGHT, TEXT, DIM = "#d4af6a", "#e6c486", "#ece3d1", "#a3967f"
GREEN, AMBER, RED = "#3fd35c", "#e8b93c", "#e0695a"
STATE_COLORS = {"ok": GREEN, "waiting": AMBER, "problem": RED, "off": DIM}
STATUS_COLORS = {"accepted": GREEN, "tentative": AMBER, "declined": RED}
CLASS_COLORS = {"warrior": "#c69b6d", "paladin": "#f48cba", "hunter": "#aad372", "rogue": "#fff468", "priest": "#ffffff",
                "shaman": "#0070dd", "mage": "#3fc7eb", "warlock": "#8788ee", "druid": "#ff7c0a"}

FONT = ("Segoe UI", 10)
SMALL = ("Segoe UI", 9)
BOLD = ("Segoe UI Semibold", 10)
HEAD = ("Segoe UI Semibold", 12)
CAPS = ("Segoe UI Semibold", 8)
TITLE = ("Palatino Linotype", 20, "bold")

SCALE = 1.0  # the screen's scaling (set in main); px() sizes things to match


def px(n):
    return round(n * SCALE)


def asset(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


# ---- Small pieces of the look ----

def label(parent, text="", font=FONT, fg=TEXT, bg=PANEL, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, anchor="w", justify="left", **kw)


def button(parent, text, command, primary=False, bg=PANEL):
    b = tk.Button(parent, text=text, command=command, font=BOLD if primary else FONT, cursor="hand2",
                  bg=GOLD if primary else RAISED, fg=BG if primary else TEXT,
                  activebackground=GOLD_LIGHT if primary else BORDER, activeforeground=BG if primary else TEXT,
                  relief="flat", bd=0, padx=px(12), pady=px(3), highlightthickness=1,
                  highlightbackground=GOLD if primary else BORDER_STRONG)
    return b


def link(parent, text, command, font=BOLD, fg=TEXT, hover=GOLD):
    """Text that opens something when clicked (underlined under the mouse)."""
    family, size = font[0], font[1]
    widget = label(parent, text, font=font, fg=fg, cursor="hand2")
    widget.bind("<Button-1>", lambda e: command())
    widget.bind("<Enter>", lambda e: widget.configure(fg=hover, font=(family, size, "underline")))
    widget.bind("<Leave>", lambda e: widget.configure(fg=fg, font=font))
    return widget


def checkbox(parent, text, variable, command):
    return tk.Checkbutton(parent, text=text, variable=variable, command=command, font=FONT, bg=PANEL, fg=TEXT,
                          activebackground=PANEL, activeforeground=TEXT, selectcolor=INSET, anchor="w",
                          highlightthickness=0, bd=0, cursor="hand2")


def dot(parent, bg=PANEL):
    size = px(10)
    canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
    canvas.create_oval(1, 1, size - 1, size - 1, fill=DIM, outline="", tags="dot")
    return canvas


def when(epoch, now=None):
    """"Today 20:00", "Tomorrow 20:00", "Sat 10 Oct 20:00"."""
    t = time.localtime(epoch)
    today = time.localtime(now or time.time())
    days = (time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400
    day = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(round(days), f"{time.strftime('%a', t)} {t.tm_mday} {time.strftime('%b', t)}")
    return day, time.strftime("%H:%M", t)


def ago(epoch):
    seconds = max(0, time.time() - epoch)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    day, clock = when(epoch)
    return f"{day.lower() if day in ('Today', 'Yesterday') else day} at {clock}"


class ScrollList(tk.Frame):
    """A list of rows that scrolls with the mouse wheel."""

    def __init__(self, parent):
        super().__init__(parent, bg=PANEL)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Gargoyle.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=PANEL)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def wheel(self, event):
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)


class Card(tk.Frame):
    """One of the status boxes along the top: a coloured dot, a heading, what's what, and
    maybe a button."""

    def __init__(self, parent, heading):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=px(12), pady=px(10))
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        self.dot = dot(top)
        self.dot.pack(side="left", padx=(0, px(6)))
        label(top, heading.upper(), font=CAPS, fg=DIM).pack(side="left")
        self.value = label(self, font=BOLD)
        self.value.pack(fill="x", pady=(px(6), 0))
        self.sub = label(self, font=SMALL, fg=DIM)
        self.sub.pack(fill="x")
        self.action = None
        self.bind("<Configure>", lambda e: self._wrap(e.width))

    def _wrap(self, width):
        for part in (self.value, self.sub):
            part.configure(wraplength=max(80, width - px(26) - 10))  # (less the padding and the labels' own edges)

    def show(self, state, value, sub="", action=None, primary=False):
        self.dot.itemconfigure("dot", fill=STATE_COLORS[state])
        self.value.configure(text=value)
        self.sub.configure(text=sub)
        wanted = action[0] if action else None
        if self.action is not None and getattr(self.action, "text_key", None) != (wanted, primary):
            self.action.destroy()
            self.action = None
        if action and self.action is None:
            self.action = button(self, action[0], action[1], primary=primary)
            self.action.text_key = (wanted, primary)
            self.action.pack(anchor="w", pady=(px(8), 0))
        elif action:
            self.action.configure(command=action[1])


# ---- The app ----

class App:
    def __init__(self, root, hidden=False):
        self.root = root
        self.config = Config()
        self.events = queue.Queue()  # from the worker threads (and the tray) to the window
        self.busy = self.linking = self.checking = False
        self.problem = None  # why the last sync didn't work, if it didn't
        self.versions = {}
        self.next_version_check = 0
        self.pumps = 0
        self.tray = None
        self.shown_key = None
        self.refreshed = 0
        self.syncer = Syncer(self.config, log=lambda text: self.events.put(("log", text)))

        root.title("Gargoyle")
        root.configure(bg=BG)
        root.geometry(f"{px(840)}x{px(690)}")
        root.minsize(px(700), px(560))
        self._style()
        self._icons()
        self._build()

        self.log(f"Gargoyle app {APP_VERSION} started.")
        if not safe_site(self.config.site):
            self.log(f"The website address {self.config.site} isn't https, so the app won't connect to it.")
        if not self.config.get("game_folder"):
            self.find_folder()
        self.syncer.load_last()
        startup.refresh()
        self.start_tray()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<MouseWheel>", self.wheel)
        root.report_callback_exception = self.report  # (problems go to the Activity tab, not nowhere)
        self.start_hidden = hidden and self.tray is not None
        self.refresh()
        root.after(PUMP_MS, self.pump)
        root.after(1000, self.tick)

    # ---- Building the window ----

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Gargoyle.Vertical.TScrollbar", background=RAISED, troughcolor=PANEL, bordercolor=PANEL,
                        lightcolor=RAISED, darkcolor=RAISED, arrowcolor=DIM, gripcount=0)
        style.map("Gargoyle.Vertical.TScrollbar", background=[("active", BORDER_STRONG)])

    def _icons(self):
        try:
            self.icon_big = tk.PhotoImage(file=str(asset("gargoyle.png")))
            self.icon_small = tk.PhotoImage(file=str(asset("gargoyle-64.png")))
            self.root.iconphoto(True, self.icon_big, self.icon_small)
            self.logo = tk.PhotoImage(file=str(asset("gargoyle-64.png" if SCALE >= 1.4 else "gargoyle-40.png")))
        except tk.TclError:
            self.logo = None

    def _build(self):
        root = self.root
        outer = tk.Frame(root, bg=BG, padx=px(18), pady=px(14))
        outer.pack(fill="both", expand=True)

        self.header = header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        if self.logo:
            tk.Label(header, image=self.logo, bg=BG).pack(side="left", padx=(0, px(12)))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        label(titles, "Gargoyle", font=TITLE, fg=GOLD, bg=BG).pack(anchor="w")
        label(titles, "Keeps your raids, signups and characters in sync between the game and your Gargoyle account.",
              font=SMALL, fg=DIM, bg=BG).pack(anchor="w")

        # A new app is out (shown when there is one).
        self.banner = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=GOLD, padx=px(12), pady=px(8))
        self.banner_text = label(self.banner, font=FONT)
        self.banner_text.pack(side="left")
        button(self.banner, "Download it", self.get_app, primary=True).pack(side="right")

        self.cards_row = tk.Frame(outer, bg=BG)
        self.cards_row.pack(fill="x", pady=(px(14), px(12)))
        self.cards = {}
        for i, (key, heading) in enumerate([("account", "Account"), ("game", "Game"), ("sync", "Last sync"),
                                            ("waiting", "Waiting to send")]):
            card = Card(self.cards_row, heading)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(10), 0))
            self.cards_row.columnconfigure(i, weight=1, uniform="cards")
            self.cards[key] = card

        tabs = tk.Frame(outer, bg=BG)
        tabs.pack(fill="x")
        self.body = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.body.pack(fill="both", expand=True)
        self.tabs, self.pages = {}, {}
        for name in ("Raids", "Characters", "Activity", "Settings"):
            tab = tk.Frame(tabs, bg=BG, cursor="hand2")
            tab.pack(side="left", padx=(0, px(4)))
            text = tk.Label(tab, text=name, font=BOLD, bg=BG, fg=DIM, padx=px(14), pady=px(6), cursor="hand2")
            text.pack()
            line = tk.Frame(tab, bg=BG, height=px(2))
            line.pack(fill="x")
            for widget in (tab, text):
                widget.bind("<Button-1>", lambda e, n=name: self.show_tab(n))
            self.tabs[name] = (text, line)
            self.pages[name] = tk.Frame(self.body, bg=PANEL, padx=px(14), pady=px(12))

        # Raids
        page = self.pages["Raids"]
        self.raids_note = label(page, font=SMALL, fg=DIM)
        self.raids_note.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.raid_list = ScrollList(page)
        self.raid_list.pack(fill="both", expand=True)

        # Characters
        page = self.pages["Characters"]
        label(page, "The characters you picked in game (in Gargoyle's Characters tab) to keep up to date on your "
              "Gargoyle account. Each is sent again whenever the game reads it again.", font=SMALL, fg=DIM,
              wraplength=px(740)).pack(side="bottom", fill="x", pady=(px(8), 0))
        self.character_list = ScrollList(page)
        self.character_list.pack(fill="both", expand=True)

        # Activity
        page = self.pages["Activity"]
        self.log_box = tk.Text(page, height=10, state="disabled", wrap="word", relief="flat", bg=INSET, fg=TEXT,
                               font=SMALL, padx=px(10), pady=px(8), highlightthickness=0, insertbackground=TEXT)
        self.log_box.pack(fill="both", expand=True)

        # Settings
        page = self.pages["Settings"]
        self.startup_on = tk.BooleanVar(value=startup.enabled())
        self.auto_update = tk.BooleanVar(value=self.config.get("auto_update", True) is not False)
        self.to_tray = tk.BooleanVar(value=self.config.get("close_to_tray", True) is not False)
        label(page, "Gargoyle", font=HEAD, fg=GOLD).pack(anchor="w")
        if startup.available():
            checkbox(page, "Start Gargoyle when Windows starts (it waits quietly in the tray)", self.startup_on,
                     self.set_startup).pack(anchor="w", pady=(px(6), 0))
        self.tray_box = checkbox(page, "Closing the window keeps Gargoyle running in the tray", self.to_tray,
                                 lambda: self.config.set("close_to_tray", self.to_tray.get()))
        self.tray_box.pack(anchor="w", pady=(px(4), 0))
        checkbox(page, "Keep the Gargoyle addon up to date", self.auto_update,
                 self.set_auto_update).pack(anchor="w", pady=(px(4), 0))

        label(page, "Game folder", font=HEAD, fg=GOLD).pack(anchor="w", pady=(px(16), 0))
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=(px(4), 0))
        button(row, "Choose…", self.choose_folder).pack(side="right", padx=(px(10), 0))
        self.folder_text = label(row, fg=DIM, wraplength=px(620))
        self.folder_text.pack(side="left", fill="x", expand=True)

        label(page, "Account", font=HEAD, fg=GOLD).pack(anchor="w", pady=(px(16), 0))
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=(px(4), 0))
        self.account_button = button(row, "", self.toggle_link)
        self.account_button.pack(side="right", padx=(px(10), 0))
        self.account_text = label(row, fg=DIM)
        self.account_text.pack(side="left", fill="x", expand=True)

        label(page, f"Gargoyle app {APP_VERSION}", font=SMALL, fg=DIM).pack(side="bottom", anchor="w")

        self.show_tab("Raids")

    def report(self, kind, error, trace):
        try:
            self.log(f"Something went wrong in the window ({kind.__name__}: {error}). If it keeps happening, "
                     "restart the app.")
        except Exception:
            pass

    def wheel(self, event):
        """The mouse wheel scrolls the list it's over."""
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ScrollList):
                widget.wheel(event)
                return
            widget = widget.master

    def show_tab(self, name):
        for tab, (text, line) in self.tabs.items():
            text.configure(fg=GOLD if tab == name else DIM)
            line.configure(bg=GOLD if tab == name else BG)
            if tab == name:
                self.pages[tab].pack(fill="both", expand=True)
            else:
                self.pages[tab].pack_forget()

    # ---- Showing things ----

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("%H:%M  ") + text + "\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > 300:
            self.log_box.delete("1.0", "101.0")  # keep the last couple of hundred lines
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def refresh(self):
        """Everything on show, brought up to date."""
        self.refreshed = time.time()
        config, syncer = self.config, self.syncer
        folder = syncer.game_folder
        installed = addon_install.installed_version(folder) if folder else None
        linked_folder = bool(folder) and addon_install.is_linked(addon_install.addons(folder) / addon_install.NAME)
        offer = addon_install.offer(self.versions)
        update = offer["version"] if offer and installed and addon_install.newer(offer["version"], installed) else None

        # Account
        user = config.get("user") or "your account"
        if config.token:
            self.cards["account"].show("ok", f"Linked as {user}", "This PC syncs with your Gargoyle account.")
        elif self.linking:
            code = getattr(self, "link_code", None)
            self.cards["account"].show("waiting", f"Your code: {code}" if code else "Waiting for you…",
                                       "Paste it on the page that opened in your browser (it's copied), then click Allow."
                                       if code else "Opening your browser…")
        else:
            self.cards["account"].show("waiting", "Not linked", "Link this PC to your Gargoyle account to sync.",
                                       ("Link account", self.toggle_link), primary=True)
        self.account_text.configure(text=f"Linked as {user}" if config.token else "Not linked")
        self.account_button.configure(text="Unlink" if config.token else "Link account")

        # Game
        game = self.cards["game"]
        if not folder:
            game.show("problem", "Game not found", "Choose the World of Warcraft folder.", ("Choose…", self.choose_folder))
        elif installed is None:
            game.show("waiting", "Addon not installed", f"Game folder: {folder.name}", ("Install the addon", self.install_addon),
                      primary=True)
        elif linked_folder:
            game.show("ok", f"Addon {installed}", f"{folder.name} (a linked folder: the app leaves it alone)")
        elif update:
            game.show("waiting", f"Addon {installed}", f"Version {update} is out.", ("Update", self.install_addon), primary=True)
        else:
            game.show("ok", f"Addon {installed}", f"Game folder: {folder.name}")
        self.folder_text.configure(text=str(folder) if folder else "Not found yet")

        # Last sync
        last = config.get("last_sync")
        last = last if isinstance(last, dict) and isinstance(last.get("at"), (int, float)) else None
        sync = self.cards["sync"]
        sync_now = ("Sync now", lambda: self.sync(force=True)) if config.token and installed else None
        if self.busy:
            sync.show("waiting", "Syncing…", last["summary"] if last else "")
        elif self.problem:
            sync.show("problem", self.problem, f"Last synced {ago(last['at'])}." if last else "Trying again soon.", sync_now)
        elif last:
            sync.show("ok", ago(last["at"]).capitalize(), str(last.get("summary", "")).capitalize(), sync_now)
        else:
            sync.show("off", "Not synced yet", "", sync_now)

        # Waiting to send
        unsent = overview.unsent(syncer.actions, config.get("sent"))
        characters = overview.characters(syncer.picked, config.get("uploaded"))
        unsent_characters = [c for c in characters if c["state"] == "waiting"]
        parts = []
        if unsent:
            parts.append(f"{len(unsent)} signup{'s' if len(unsent) != 1 else ''}")
        if unsent_characters:
            parts.append(f"{len(unsent_characters)} character{'s' if len(unsent_characters) != 1 else ''}")
        if parts:
            self.cards["waiting"].show("waiting", " and ".join(parts), "Sent with the next sync." if config.token
                                       else "Link your account to send them.")
        else:
            self.cards["waiting"].show("ok", "Nothing waiting", "Signups made in game are sent after a /reload or logging out.")

        # A new app?
        app_update = addon_install.app_update(self.versions, APP_VERSION)
        if app_update:
            self.banner_text.configure(text=f"A new version of the Gargoyle app is out ({app_update}). You have {APP_VERSION}.")
            self.banner.pack(fill="x", pady=(px(12), 0), after=self.header)
        else:
            self.banner.pack_forget()

        # The lists, rebuilt only when what they show has changed.
        raids = overview.raids(syncer.table, syncer.actions, config.get("sent"), time.time())
        key = (repr(raids), repr(characters), bool(config.token), time.strftime("%Y%m%d"))
        if key != self.shown_key:
            self.shown_key = key
            self.show_raids(raids)
            self.show_characters(characters)

        if self.tray:
            self.tray.title = "Gargoyle" + (f": synced {ago(last['at'])}" if last and config.token else "")

    def show_raids(self, raids):
        rows = self.raid_list
        rows.clear()
        if not self.config.token:
            empty = "Link your account to see your guilds' upcoming raids here."
        elif self.syncer.table is None:
            empty = "Your raids show here after the first sync."
        else:
            empty = "No upcoming raids in your guilds."
        if not raids:
            label(rows.inner, empty, fg=DIM).pack(anchor="w", pady=px(6))
        for i, raid in enumerate(raids):
            if i:
                tk.Frame(rows.inner, bg=BORDER, height=1).pack(fill="x")
            row = tk.Frame(rows.inner, bg=PANEL, pady=px(8))
            row.pack(fill="x")
            day, clock = when(raid["start"])
            date = tk.Frame(row, bg=PANEL, width=px(110))
            date.pack(side="left", fill="y")
            date.pack_propagate(False)
            label(date, day, font=BOLD, fg=GOLD).pack(anchor="w")
            label(date, clock, font=SMALL, fg=DIM).pack(anchor="w")
            status = tk.Frame(row, bg=PANEL)
            status.pack(side="right", padx=(px(10), px(4)), anchor="n")
            label(status, overview.signup_text(raid), font=BOLD, fg=STATUS_COLORS.get(raid["status"], DIM)).pack(anchor="e")
            if raid["waiting"]:
                label(status, "made in game, waiting to send", font=SMALL, fg=AMBER).pack(anchor="e")
            path = overview.raid_path(raid)
            if path:
                link(status, "Change it on the website ›" if raid["status"] else "Sign up on the website ›",
                     lambda p=path: self.open_site(p), font=SMALL, fg=DIM).pack(anchor="e")
            middle = tk.Frame(row, bg=PANEL)
            middle.pack(side="left", fill="x", expand=True, anchor="n")
            if path:
                link(middle, raid["title"], lambda p=path: self.open_site(p)).pack(anchor="w")
            else:
                label(middle, raid["title"], font=BOLD).pack(anchor="w")
            label(middle, raid["guild"] + (f"  ·  {raid['size']} players" if raid.get("size") else ""),
                  font=SMALL, fg=DIM).pack(anchor="w")
        if raids:
            self.raids_note.configure(text="Sign up in game (Gargoyle's Raids tab), on the website or in Discord. "
                                           "The game shows changes after a /reload.")
        else:
            self.raids_note.configure(text="")

    def show_characters(self, characters):
        rows = self.character_list
        rows.clear()
        if not characters:
            label(rows.inner, "No characters picked yet. In game, open Gargoyle's Characters tab and pick the ones "
                  "to keep up to date.", fg=DIM, wraplength=px(700)).pack(anchor="w", pady=px(6))
        for i, c in enumerate(characters):
            if i:
                tk.Frame(rows.inner, bg=BORDER, height=1).pack(fill="x")
            row = tk.Frame(rows.inner, bg=PANEL, pady=px(8))
            row.pack(fill="x")
            right = tk.Frame(row, bg=PANEL)
            right.pack(side="right", padx=(px(10), px(4)))
            label(right, c["text"], font=BOLD, fg=STATE_COLORS[c["state"]], wraplength=px(330)).pack(anchor="e")
            day, clock = when(c["read"])
            label(right, f"Read in game {day.lower() if day in ('Today', 'Yesterday', 'Tomorrow') else day} at {clock}",
                  font=SMALL, fg=DIM).pack(anchor="e")
            left = tk.Frame(row, bg=PANEL)
            left.pack(side="left", fill="x", expand=True)
            label(left, c["name"], font=BOLD, fg=CLASS_COLORS.get(c["token"], TEXT)).pack(anchor="w")
            label(left, " ".join(x for x in (f"Level {c['level']}" if c.get("level") else "", c["class"]) if x),
                  font=SMALL, fg=DIM).pack(anchor="w")

    def pump(self):
        # (next round booked first, so a problem in this one can't stop them; in the tray a
        # slower look at what's come in is plenty)
        self.pump_after = self.root.after(PUMP_MS if self.root.state() != "withdrawn" else PUMP_MS * 4, self.pump)
        changed = False
        while not self.events.empty():
            kind, *rest = self.events.get()
            changed = True
            if kind == "log":
                self.log(rest[0])
            elif kind == "code":  # (linking: the code, ready to paste on the website)
                self.link_code = rest[0]
                self.root.clipboard_clear()
                self.root.clipboard_append(rest[0])
            elif kind == "notify":
                self.notify(rest[0])
            elif kind == "open":
                self.open()
            elif kind == "sync":
                self.sync(force=True)
            elif kind == "quit":
                self.quit()
                return
        self.pumps += 1
        if self.pumps % 4 == 0 or self.root.state() == "withdrawn":  # (about once a second)
            if take_file(QUIT_FILE):
                self.quit()
                return
            if take_file(SHOW_FILE):  # (someone started the app again while it was running)
                self.open()
        if changed:
            self.refresh()

    # ---- The tray ----

    def start_tray(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:  # (running from source without them: no tray, closing quits)
            self.tray_box.pack_forget()
            return
        put = self.events.put
        menu = pystray.Menu(
            pystray.MenuItem("Open Gargoyle", lambda: put(("open",)), default=True),
            pystray.MenuItem("Sync now", lambda: put(("sync",))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Gargoyle", lambda: put(("quit",))),
        )
        self.tray = pystray.Icon("Gargoyle", Image.open(asset("gargoyle-64.png")), "Gargoyle", menu)
        self.tray.run_detached()

    def notify(self, text):
        """A Windows notification from the tray icon, when the window isn't open."""
        if self.tray and self.root.state() == "withdrawn":
            try:
                self.tray.notify(text, "Gargoyle")
            except Exception:  # (notifications switched off, or not supported)
                pass

    def open(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def close(self):
        if self.tray and self.to_tray.get():
            self.root.withdraw()
            if not self.config.get("told_tray"):
                self.config.set("told_tray", True)
                self.tray.notify("Gargoyle keeps syncing in the tray. Right-click its icon to sync now or quit.", "Gargoyle")
        else:
            self.quit()

    def quit(self):
        if getattr(self, "pump_after", None):
            self.root.after_cancel(self.pump_after)
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    # ---- Settings ----

    def set_startup(self):
        try:
            startup.set_enabled(self.startup_on.get())
        except OSError as exc:
            self.log(f"Couldn't change starting with Windows ({exc.__class__.__name__}).")
        self.startup_on.set(startup.enabled())

    def set_auto_update(self):
        self.config.set("auto_update", self.auto_update.get())
        if self.auto_update.get():
            self.check_versions()

    def open_site(self, path):
        """A page on the website (only ever the website the app syncs with)."""
        if safe_site(self.config.site) and path.startswith("/"):
            webbrowser.open(self.config.site + path)

    def get_app(self):
        """The new app's installer, from its GitHub release (running it updates this copy)."""
        url = addon_install.app_download(self.versions) or f"{RELEASES}/latest"
        if url.startswith(RELEASES + "/"):
            webbrowser.open(url)

    # ---- Linking ----

    def toggle_link(self):
        if self.config.token:
            if messagebox.askyesno("Gargoyle", "Unlink this PC from your Gargoyle account?"):
                threading.Thread(target=self._unlink, daemon=True).start()
        elif not self.linking:
            self.linking = True
            threading.Thread(target=self._link, daemon=True).start()
            self.refresh()

    def _unlink(self):
        self.syncer.unlink()
        self.syncer.table = None  # (that account's raids aren't shown any more)
        self.config.set("last_sync", None)
        self.events.put(("log", "Unlinked."))

    def _link(self):
        try:
            start = self.syncer.start_link()
            self.events.put(("code", start["user_code"]))
            self.events.put(("log", f"Your code is {start['user_code']} (copied). Paste it on the page that opened "
                                    "in your browser, then click Allow."))
            webbrowser.open(start["verify_url"])
            deadline = time.time() + int(start.get("expires_in", 600))
            while time.time() < deadline:
                time.sleep(max(2, int(start.get("interval", 5))))
                status = self.syncer.finish_link(start["device_code"])
                if status == "linked":
                    self.events.put(("log", f"Linked as {self.config.get('user')}."))
                    self.syncer.last_refresh = 0  # sync straight away
                    return
                if status != "pending":
                    break
            self.events.put(("log", "The code expired before it was allowed. Click Link to try again."))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            self.events.put(("log", f"Couldn't link with the website ({exc.__class__.__name__}). Try again in a moment."))
        finally:
            self.linking = False
            self.link_code = None
            self.events.put(("refresh",))

    # ---- The game folder ----

    def use_folder(self, folder):
        self.config.set("game_folder", str(folder))
        self.syncer.seen = {}
        self.syncer.load_last()
        self.check_versions()

    def find_folder(self):
        found = wow_paths.find_game_folders()
        if found:
            self.config.set("game_folder", str(found[0]))
            self.log(f"Found the game in {found[0]}." + (" (Others too: Settings, Choose… to switch.)" if len(found) > 1 else ""))
            return
        versions = wow_paths.find_game_folders(with_addon=False)
        if len(versions) == 1:
            self.config.set("game_folder", str(versions[0]))
            self.log(f"Found the game in {versions[0]}. The Gargoyle addon isn't installed there yet.")
        elif versions:
            self.log("Found the game in more than one folder (" + ", ".join(str(v) for v in versions)
                     + "). Choose the one you play on.")

    def choose_folder(self):
        chosen = filedialog.askdirectory(title="The World of Warcraft folder (or the version folder inside it)")
        if not chosen:
            return
        with_addon = wow_paths.game_folders(chosen)
        found = with_addon or wow_paths.version_folders(chosen)
        if not found:
            messagebox.showwarning("Gargoyle", "That doesn't look like a World of Warcraft folder. Choose the folder "
                                   "the game is installed in, or the version folder inside it (like _classic_).")
            return
        if len(found) > 1 and not with_addon:
            messagebox.showinfo("Gargoyle", "That folder has more than one version of the game in it ("
                                + ", ".join(f.name for f in found) + "). Choose the one you play on.")
            return
        self.use_folder(found[0])
        self.log(f"Using {found[0]}.")
        self.refresh()

    # ---- The addon and app versions ----

    def install_addon(self):
        self.check_versions(install=True)

    def check_versions(self, install=False):
        if self.checking:
            return
        self.checking = True
        threading.Thread(target=self._check_versions, args=(install,), daemon=True).start()

    def _check_versions(self, install):
        put = self.events.put
        self.next_version_check = time.time() + VERSION_RETRY_SECONDS  # (unless it gets through)
        try:
            self.versions = self.syncer.versions()
            self.next_version_check = time.time() + VERSION_CHECK_SECONDS
            folder = self.syncer.game_folder
            offer = addon_install.offer(self.versions)
            if not folder:
                return
            current = addon_install.installed_version(folder)
            if not offer:
                if install:
                    put(("log", "The addon download isn't available right now. Try again later."))
                return
            if not addon_install.newer(offer["version"], current):
                if install:
                    put(("log", f"The Gargoyle addon is up to date ({current})."))
                return
            linked = addon_install.is_linked(addon_install.addons(folder) / addon_install.NAME)
            if not install and (current is None or linked or self.config.get("auto_update", True) is False):
                return  # (installing the first time, or updating with that switched off, waits for a click)
            signed = self.syncer.signed_addon(offer)  # (Gargoyle's release key signed it, or nothing's installed)
            data = self.syncer.download(offer["url"], addon_install.MAX_DOWNLOAD)
            addon_install.check_download(data, offer)
            version = addon_install.install(folder, data, signed)
            text = (f"Installed the Gargoyle addon {version}." if current is None
                    else f"Updated the Gargoyle addon to {version}.")
            put(("log", text + " If the game is open, restart it to load it."))
            put(("notify", text + " If the game is open, restart it to load it."))
            self.syncer.last_refresh = 0  # sync now (the new copy needs its raid data)
        except requests.RequestException:
            if install:
                put(("log", "Couldn't reach GitHub to get the addon. Try again in a moment."))
        except (addon_install.InstallError, signing.SignatureError, OSError, ValueError) as exc:  # (ValueError: an answer that made no sense)
            put(("log", f"Couldn't install the addon: {exc}."))
        except Exception as exc:  # (anything else: said, rather than the checks quietly stopping)
            put(("log", f"Checking for updates didn't work ({exc.__class__.__name__})."))
        finally:
            self.checking = False
            put(("refresh",))

    # ---- Syncing ----

    def tick(self):
        self.root.after(TICK_MS, self.tick)  # (booked first, like pump)
        folder = self.syncer.game_folder
        if self.config.token and folder and not self.busy and wow_paths.has_addon(folder) and self.syncer.due():
            self.sync()
        if time.time() >= self.next_version_check:
            self.check_versions()
        if time.time() - self.refreshed >= 30:
            self.refresh()  # ("5 minutes ago" moves on)

    def sync(self, force=False):
        if self.busy:
            return
        if not self.config.token:
            self.log("Link your account first.")
            return
        folder = self.syncer.game_folder
        if not folder or not wow_paths.has_addon(folder):
            self.log("Install the Gargoyle addon first (or choose the game folder that has it).")
            return
        self.busy = True
        self.refresh()
        threading.Thread(target=self._sync, daemon=True).start()

    def _sync(self):
        try:
            summary = self.syncer.run()
            self.problem = None
            self.config.set("last_sync", {"at": int(time.time()), "summary": summary})
        except Unlinked:
            self.config.token = None
            self.events.put(("log", "This PC was unlinked from your account. Link it again to keep syncing."))
        except requests.RequestException:
            self.problem = "Couldn't reach gargoyle.gg"
            self.syncer.retry_at = time.time() + 60
        except Exception as exc:  # (shown rather than silently stopping the syncing)
            self.problem = "Sync didn't work"
            self.events.put(("log", f"Sync didn't work: {exc}"))
            self.syncer.retry_at = time.time() + 60
        finally:
            self.busy = False
            self.events.put(("refresh",))


# ---- Starting up ----

_mutex = None


def take_file(name):
    """Is this note in the settings folder? (It's removed.)"""
    path = config_folder() / name
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        pass
    return True


def already_running():
    """Is the app running already (for this Windows user)? If so it's asked to show itself."""
    global _mutex
    if sys.platform != "win32":
        return False
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    _mutex = kernel.CreateMutexW(None, False, "Local\\GargoyleApp")
    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
        take_file(QUIT_FILE)  # (left over from an installer: not meant for this start)
        return False
    try:
        config_folder().mkdir(parents=True, exist_ok=True)
        (config_folder() / SHOW_FILE).write_text("show")
    except OSError:
        pass
    return True


def windows_look(root):
    """Sharp text on scaled screens, Gargoyle's own taskbar icon, and a dark title bar."""
    global SCALE
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Gargoyle.App")
    except (AttributeError, OSError):
        pass
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer Windows 10 and 11, then older 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except (AttributeError, OSError):
        pass


def main():
    if already_running():
        return
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.withdraw()  # (shown once it's built, so it doesn't flash white first)
    windows_look(root)
    app = App(root, hidden="--tray" in sys.argv[1:])
    if not app.start_hidden:
        root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
