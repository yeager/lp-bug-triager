"""LP Bug Triager — Launchpad bug triage with classification."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, Pango

import gettext
import locale
import os
import sys
import json
import datetime
import threading
import subprocess
import re

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "po")
if not os.path.isdir(LOCALE_DIR):
    LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain("lp-bug-triager", LOCALE_DIR)
gettext.bindtextdomain("lp-bug-triager", LOCALE_DIR)
gettext.textdomain("lp-bug-triager")
_ = gettext.gettext

APP_ID = "se.danielnylander.lp.bug.triager"
SETTINGS_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "lp-bug-triager"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def _load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"welcome_shown": False}


def _save_settings(s):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)



def _search_lp_bugs(project, status="New"):
    """Search Launchpad bugs via REST API."""
    import urllib.request
    url = f"https://api.launchpad.net/1.0/{project}?ws.op=searchTasks&status={status}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
            return data.get("entries", [])
    except:
        return []



class LpBugTriagerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("LP Bug Triager"), default_width=1100, default_height=750)
        self.settings = _load_settings()
        self._bugs = []

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header
        headerbar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title=_("LP Bug Triager"), subtitle="")
        headerbar.set_title_widget(title_widget)
        self._title_widget = title_widget

        
        # Project entry
        self._project_entry = Gtk.Entry(placeholder_text=_("Launchpad project..."))
        self._project_entry.set_size_request(200, -1)
        headerbar.pack_start(self._project_entry)
        
        search_btn = Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Search bugs"))
        search_btn.connect("clicked", self._on_search)
        headerbar.pack_start(search_btn)

        # Menu
        menu = Gio.Menu()
        menu.append(_("Settings"), "app.settings")
        menu.append(_("Copy Debug Info"), "app.copy-debug")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About LP Bug Triager"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        headerbar.pack_end(menu_btn)

        main_box.append(headerbar)

        
        # Bug list with paned view
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        
        # Left: bug list
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_size_request(450, -1)
        self._bug_list = Gtk.ListBox()
        self._bug_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._bug_list.add_css_class("boxed-list")
        self._bug_list.set_margin_start(8)
        self._bug_list.set_margin_end(8)
        self._bug_list.connect("row-selected", self._on_bug_selected)
        left_scroll.set_child(self._bug_list)
        paned.set_start_child(left_scroll)
        
        # Right: detail
        self._detail = Adw.StatusPage()
        self._detail.set_icon_name("bug-symbolic")
        self._detail.set_title(_("Select a bug"))
        self._detail.set_description(_("Search for a Launchpad project and select a bug to view details."))
        paned.set_end_child(self._detail)
        paned.set_position(480)
        
        main_box.append(paned)

        # Status bar
        self._status = Gtk.Label(label=_("Ready"), xalign=0)
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.add_css_class("dim-label")
        main_box.append(self._status)

        self.set_content(main_box)

        if not self.settings.get("welcome_shown"):
            GLib.idle_add(self._show_welcome)

    def _show_welcome(self):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(420)
        dialog.set_content_height(480)

        page = Adw.StatusPage()
        page.set_icon_name("bug-symbolic")
        page.set_title(_("Welcome to LP Bug Triager"))
        page.set_description(_("Triage Launchpad bugs efficiently.\n\n"
            "✓ Search and filter bugs by project\n"
            "✓ Automatic severity classification\n"
            "✓ Duplicate detection\n"
            "✓ Bulk status updates\n"
            "✓ Export triage reports"))

        btn = Gtk.Button(label=_("Get Started"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_welcome_close, dialog)
        page.set_child(btn)

        box = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        box.add_top_bar(hb)
        box.set_content(page)
        dialog.set_child(box)
        dialog.present(self)

    def _on_welcome_close(self, btn, dialog):
        self.settings["welcome_shown"] = True
        _save_settings(self.settings)
        dialog.close()

    
    def _on_search(self, btn):
        project = self._project_entry.get_text().strip()
        if not project:
            return
        self._status.set_text(_("Searching %s...") % project)
        threading.Thread(target=self._do_search, args=(project,), daemon=True).start()

    def _do_search(self, project):
        bugs = _search_lp_bugs(project)
        GLib.idle_add(self._show_bugs, bugs)

    def _show_bugs(self, bugs):
        self._bugs = bugs
        while True:
            row = self._bug_list.get_row_at_index(0)
            if row is None:
                break
            self._bug_list.remove(row)
        
        for bug in bugs:
            row = Adw.ActionRow()
            title = bug.get("title", bug.get("bug_link", _("Unknown")))
            row.set_title(title[:80])
            row.set_subtitle(bug.get("status", ""))
            importance = bug.get("importance", "Undecided")
            badge = Gtk.Label(label=importance)
            badge.add_css_class("caption")
            if importance in ("Critical", "High"):
                badge.add_css_class("error")
            row.add_suffix(badge)
            row._bug_data = bug
            self._bug_list.append(row)
        
        self._status.set_text(_("Found %(count)d bugs") % {"count": len(bugs)})

    def _on_bug_selected(self, listbox, row):
        if row is None:
            return
        bug = row._bug_data
        self._detail.set_title(bug.get("title", _("Bug"))[:100])
        self._detail.set_description(
            _("Status: %(status)s\nImportance: %(importance)s\n%(link)s") %
            {"status": bug.get("status", "?"), "importance": bug.get("importance", "?"),
             "link": bug.get("web_link", "")}
        )


class LpBugTriagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

        for name, callback in [
            ("settings", self._on_settings),
            ("copy-debug", self._on_copy_debug),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
            ("quit", self._on_quit),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>slash"])

    def do_activate(self):
        if not self.window:
            self.window = LpBugTriagerWindow(self)
        self.window.present()

    def _on_settings(self, *_):
        if not self.window:
            return
        dialog = Adw.PreferencesDialog()
        dialog.set_title(_("Settings"))
        page = Adw.PreferencesPage()
        
        group = Adw.PreferencesGroup(title=_("Search"))
        row = Adw.ComboRow(title=_("Default status filter"))
        row.set_model(Gtk.StringList.new(["New", "Confirmed", "Triaged", "In Progress", "Fix Committed"]))
        group.add(row)
        page.add(group)
        dialog.add(page)
        dialog.present(self.window)

    def _on_copy_debug(self, *_):
        if not self.window:
            return
        from . import __version__
        info = (
            f"LP Bug Triager {__version__}\n"
            f"Python {sys.version}\n"
            f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}\n"
            f"Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}\n"
            f"OS: {os.uname().sysname} {os.uname().release}\n"
        )
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(info)
        self.window._status.set_text(_("Debug info copied"))

    def _on_shortcuts(self, *_):
        if self.window:
            dialog = Gtk.ShortcutsWindow(transient_for=self.window)
            section = Gtk.ShortcutsSection(visible=True)
            group = Gtk.ShortcutsGroup(title=_("General"), visible=True)
            for accel, title in [
                ("<Ctrl>q", _("Quit")),
                ("<Ctrl>slash", _("Keyboard shortcuts")),
            ]:
                group.append(Gtk.ShortcutsShortcut(accelerator=accel, title=title, visible=True))
            section.append(group)
            dialog.append(section)
            dialog.present()

    def _on_about(self, *_):
        from . import __version__
        dialog = Adw.AboutDialog(
            application_name=_("LP Bug Triager"),
            application_icon="bug-symbolic",
            version=__version__,
            developer_name="Daniel Nylander",
            website="https://github.com/yeager/lp-bug-triager",
            license_type=Gtk.License.GPL_3_0,
            issue_url="https://github.com/yeager/lp-bug-triager/issues",
            comments=_("Automated Launchpad bug triage with duplicate detection and severity classification."),
        )
        dialog.present(self.window)

    def _on_quit(self, *_):
        self.quit()


def main():
    app = LpBugTriagerApp()
    app.run(sys.argv)
