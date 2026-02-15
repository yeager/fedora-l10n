#!/usr/bin/env python3
"""Fedora Translation Status — Main application."""

import csv
import gettext
import json
import locale
import sys
import threading
import webbrowser

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, Pango, Gdk  # noqa: E402

import json as _json
import platform as _platform
from pathlib import Path as _Path

# Optional desktop notifications
try:
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify as _Notify
    HAS_NOTIFY = True
except (ValueError, ImportError):
    HAS_NOTIFY = False

from fedora_l10n import __version__, __app_id__
from fedora_l10n.api import (
    get_projects, get_language_statistics, get_components,
    get_component_statistics, clear_cache, has_api_key, save_api_key,
)

# Gettext setup
gettext.bindtextdomain("fedora-l10n", "/usr/share/locale")
gettext.textdomain("fedora-l10n")
_ = gettext.gettext

_NOTIFY_APP = "fedora-l10n"


def _notify_config_path():
    return _Path(GLib.get_user_config_dir()) / _NOTIFY_APP / "notifications.json"


def _load_notify_config():
    try:
        return _json.loads(_notify_config_path().read_text())
    except Exception:
        return {"enabled": False}


def _save_notify_config(config):
    p = _notify_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(config))


def _send_notification(summary, body="", icon="dialog-information"):
    if HAS_NOTIFY and _load_notify_config().get("enabled"):
        try:
            n = _Notify.Notification.new(summary, body, icon)
            n.show()
        except Exception:
            pass


def _get_system_info():
    return "\n".join([
        f"App: Fedora Translation Status",
        f"Version: {__version__}",
        f"GTK: {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
        f"Adw: {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}",
        f"Python: {_platform.python_version()}",
        f"OS: {_platform.system()} {_platform.release()} ({_platform.machine()})",
    ])


def _detect_language() -> str:
    """Detect system language, return 2-letter code."""
    try:
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc.split("_")[0]
    except Exception:
        pass
    return "en"


def _color_for_percent(pct: float) -> str:
    """Return CSS color for translation percentage."""
    if pct >= 100:
        return "#26a269"
    elif pct >= 80:
        return "#2ec27e"
    elif pct >= 50:
        return "#e5a50a"
    elif pct >= 20:
        return "#ff7800"
    else:
        return "#c01c28"


class ProjectRow(Gtk.ListBoxRow):
    """A row showing a project with its translation percentage."""

    def __init__(self, project_data: dict, translated_pct: float):
        super().__init__()
        self.project_data = project_data
        self.slug = project_data.get("slug", "")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Project name
        name_label = Gtk.Label(label=project_data.get("name", self.slug))
        name_label.set_halign(Gtk.Align.START)
        name_label.set_hexpand(True)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(name_label)

        # Percentage bar
        bar = Gtk.LevelBar()
        bar.set_min_value(0)
        bar.set_max_value(100)
        bar.set_value(min(translated_pct, 100))
        bar.set_size_request(120, -1)
        bar.set_valign(Gtk.Align.CENTER)
        box.append(bar)

        # Percentage label
        pct_label = Gtk.Label(label=f"{translated_pct:.0f}%")
        pct_label.set_width_chars(5)
        color = _color_for_percent(translated_pct)
        pct_label.set_markup(f'<span color="{color}" weight="bold">{translated_pct:.0f}%</span>')
        box.append(pct_label)

        self.set_child(box)


class ComponentRow(Gtk.ListBoxRow):
    """A row showing a component with its translation percentage."""

    def __init__(self, name: str, slug: str, translated_pct: float, project_slug: str):
        super().__init__()
        self.component_slug = slug
        self.project_slug = project_slug

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        name_label = Gtk.Label(label=name)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_hexpand(True)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(name_label)

        bar = Gtk.LevelBar()
        bar.set_min_value(0)
        bar.set_max_value(100)
        bar.set_value(min(translated_pct, 100))
        bar.set_size_request(120, -1)
        bar.set_valign(Gtk.Align.CENTER)
        box.append(bar)

        pct_label = Gtk.Label()
        pct_label.set_width_chars(5)
        color = _color_for_percent(translated_pct)
        pct_label.set_markup(f'<span color="{color}" weight="bold">{translated_pct:.0f}%</span>')
        box.append(pct_label)

        # Link button
        url = f"https://translate.fedoraproject.org/projects/{project_slug}/{slug}/"
        link_btn = Gtk.Button(icon_name="web-browser-symbolic")
        link_btn.set_tooltip_text(_("Open in Weblate"))
        link_btn.add_css_class("flat")
        link_btn.connect("clicked", lambda b: webbrowser.open(url))
        box.append(link_btn)

        self.set_child(box)


def _setup_heatmap_css():
    """Install heatmap CSS classes."""
    css = b"""
    .heatmap-green { background-color: #26a269; color: white; border-radius: 8px; }
    .heatmap-yellow { background-color: #e5a50a; color: white; border-radius: 8px; }
    .heatmap-orange { background-color: #ff7800; color: white; border-radius: 8px; }
    .heatmap-red { background-color: #c01c28; color: white; border-radius: 8px; }
    .heatmap-gray { background-color: #77767b; color: white; border-radius: 8px; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _heatmap_css_class(pct):
    if pct >= 100:
        return "heatmap-green"
    elif pct >= 75:
        return "heatmap-yellow"
    elif pct >= 50:
        return "heatmap-orange"
    elif pct > 0:
        return "heatmap-red"
    return "heatmap-gray"


def _create_heatmap_cell(name, pct, tooltip=""):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_size_request(140, 64)
    box.add_css_class(_heatmap_css_class(pct))
    box.set_margin_start(4)
    box.set_margin_end(4)
    box.set_margin_top(4)
    box.set_margin_bottom(4)
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)

    label = Gtk.Label(label=name)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(18)
    label.set_margin_top(6)
    label.set_margin_start(6)
    label.set_margin_end(6)
    box.append(label)

    pct_label = Gtk.Label(label=f"{pct:.0f}%")
    pct_label.set_margin_bottom(6)
    box.append(pct_label)

    if tooltip:
        box.set_tooltip_text(tooltip)

    return box


class FedoraL10nWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(_("Fedora Translation Status"))
        self.set_default_size(800, 600)

        self._lang = _detect_language()
        self._projects = []
        self._filter_text = ""
        self._heatmap_mode = False

        _setup_heatmap_css()

        # Main layout
        self._build_ui()

        # Load data
        self._load_projects()

    def _build_ui(self):
        # Header bar
        header = Adw.HeaderBar()

        # Back button (hidden initially)
        self._back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        self._back_btn.set_tooltip_text(_("Back to projects"))
        self._back_btn.connect("clicked", self._on_back)
        self._back_btn.set_visible(False)
        header.pack_start(self._back_btn)

        # Heatmap toggle
        self._heatmap_btn = Gtk.ToggleButton(icon_name="view-grid-symbolic")
        self._heatmap_btn.set_tooltip_text(_("Toggle heatmap view"))
        self._heatmap_btn.connect("toggled", self._on_heatmap_toggled)
        header.pack_start(self._heatmap_btn)

        # Menu button
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append(_("Refresh"), "win.refresh")
        menu.append(_("API Key…"), "win.api-key")
        menu.append(_("Clear Cache"), "win.clear-cache")
        menu.append(_("Notifications"), "win.toggle-notifications")
        menu.append(_("About"), "win.about")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        # Export button
        export_btn = Gtk.Button(icon_name="document-save-symbolic",
                                tooltip_text=_("Export data"))
        export_btn.connect("clicked", self._on_export_clicked)
        header.pack_end(export_btn)

        # Theme toggle
        self._theme_btn = Gtk.Button(icon_name="weather-clear-night-symbolic",
                                     tooltip_text="Toggle dark/light theme")
        self._theme_btn.connect("clicked", self._on_theme_toggle)
        header.pack_end(self._theme_btn)

        # Actions
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda a, p: self._load_projects())
        self.add_action(refresh_action)

        apikey_action = Gio.SimpleAction.new("api-key", None)
        apikey_action.connect("activate", self._on_api_key)
        self.add_action(apikey_action)

        cache_action = Gio.SimpleAction.new("clear-cache", None)
        cache_action.connect("activate", self._on_clear_cache)
        self.add_action(cache_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        notif_action = Gio.SimpleAction.new("toggle-notifications", None)
        notif_action.connect("activate", self._on_toggle_notifications)
        self.add_action(notif_action)

        # Search bar
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(_("Filter projects…"))
        self._search_entry.connect("search-changed", self._on_search_changed)

        # Language entry
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lang_label = Gtk.Label(label=_("Language:"))
        self._lang_entry = Gtk.Entry()
        self._lang_entry.set_text(self._lang)
        self._lang_entry.set_width_chars(5)
        self._lang_entry.set_max_width_chars(5)
        self._lang_entry.connect("activate", self._on_lang_changed)
        lang_box.append(lang_label)
        lang_box.append(self._lang_entry)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        search_box.set_margin_start(12)
        search_box.set_margin_end(12)
        search_box.set_margin_top(6)
        search_box.set_margin_bottom(6)
        self._search_entry.set_hexpand(True)
        search_box.append(self._search_entry)
        search_box.append(lang_box)

        # Navigation stack
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        # Project list page
        project_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self._project_list = Gtk.ListBox()
        self._project_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._project_list.connect("row-activated", self._on_project_activated)
        self._project_list.add_css_class("boxed-list")
        scrolled.set_child(self._project_list)
        project_page.append(scrolled)
        self._stack.add_named(project_page, "projects")

        # Heatmap page for projects
        heatmap_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heatmap_scrolled = Gtk.ScrolledWindow()
        heatmap_scrolled.set_vexpand(True)
        self._heatmap_flow = Gtk.FlowBox()
        self._heatmap_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._heatmap_flow.set_homogeneous(True)
        self._heatmap_flow.set_min_children_per_line(3)
        self._heatmap_flow.set_max_children_per_line(8)
        self._heatmap_flow.set_column_spacing(4)
        self._heatmap_flow.set_row_spacing(4)
        self._heatmap_flow.set_margin_start(12)
        self._heatmap_flow.set_margin_end(12)
        self._heatmap_flow.set_margin_top(12)
        self._heatmap_flow.set_margin_bottom(12)
        heatmap_scrolled.set_child(self._heatmap_flow)
        heatmap_page.append(heatmap_scrolled)
        self._stack.add_named(heatmap_page, "heatmap")

        # Component list page
        component_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        comp_scrolled = Gtk.ScrolledWindow()
        comp_scrolled.set_vexpand(True)
        self._component_list = Gtk.ListBox()
        self._component_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._component_list.add_css_class("boxed-list")
        comp_scrolled.set_child(self._component_list)
        component_page.append(comp_scrolled)
        self._stack.add_named(component_page, "components")

        # Spinner for loading
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        spinner_box.set_valign(Gtk.Align.CENTER)
        spinner_box.set_vexpand(True)
        spinner_box.append(self._spinner)
        self._status_label = Gtk.Label(label=_("Loading projects…"))
        spinner_box.append(self._status_label)
        self._stack.add_named(spinner_box, "loading")

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(header)
        main_box.append(search_box)
        main_box.append(self._stack)

        # Status bar
        self._status_bar = Gtk.Label(label="", halign=Gtk.Align.START,
                                     margin_start=12, margin_end=12, margin_bottom=4)
        self._status_bar.add_css_class("dim-label")
        self._status_bar.add_css_class("caption")
        main_box.append(self._status_bar)

        self.set_content(main_box)

    def _load_projects(self):
        self._stack.set_visible_child_name("loading")
        self._spinner.start()
        self._status_label.set_text(_("Loading projects…"))

        def worker():
            try:
                projects = get_projects(
                    callback=lambda p, t: GLib.idle_add(
                        self._status_label.set_text,
                        _("Loading projects… page {page}/{total}").format(page=p, total=t)
                    )
                )
                # Fetch per-language stats for each project
                enriched = []
                for i, proj in enumerate(projects):
                    slug = proj.get("slug", "")
                    try:
                        stats = get_language_statistics(slug, self._lang)
                        pct = stats.get("translated_percent", 0) if stats else 0
                    except Exception:
                        pct = 0
                    enriched.append((proj, pct))
                    if (i + 1) % 10 == 0:
                        GLib.idle_add(
                            self._status_label.set_text,
                            _("Loading statistics… {n}/{total}").format(n=i + 1, total=len(projects))
                        )
                GLib.idle_add(self._populate_projects, enriched)
            except Exception as e:
                GLib.idle_add(self._show_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_projects(self, enriched):
        self._projects = enriched
        self._spinner.stop()
        # Check for notification-worthy changes
        low = [p.get("name", p.get("slug", "?")) for p, pct in enriched if pct < 50 and pct > 0]
        if low:
            _send_notification(
                _("Fedora L10n: Low translations"),
                _("{count} projects below 50%: {names}").format(
                    count=len(low), names=", ".join(low[:5])),
                "fedora-l10n")
        self._rebuild_project_list()
        if self._heatmap_mode:
            self._rebuild_heatmap()
            self._stack.set_visible_child_name("heatmap")
        else:
            self._stack.set_visible_child_name("projects")

    def _rebuild_project_list(self):
        # Clear
        while True:
            row = self._project_list.get_row_at_index(0)
            if row is None:
                break
            self._project_list.remove(row)

        ft = self._filter_text.lower()
        for proj, pct in sorted(self._projects, key=lambda x: x[1], reverse=True):
            name = proj.get("name", proj.get("slug", ""))
            if ft and ft not in name.lower() and ft not in proj.get("slug", "").lower():
                continue
            self._project_list.append(ProjectRow(proj, pct))

    def _on_search_changed(self, entry):
        self._filter_text = entry.get_text()
        self._rebuild_project_list()

    def _on_export_clicked(self, *_args):
        dialog = Adw.MessageDialog(transient_for=self,
                                   heading=_("Export Data"),
                                   body=_("Choose export format:"))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("csv", "CSV")
        dialog.add_response("json", "JSON")
        dialog.set_response_appearance("csv", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_export_format_chosen)
        dialog.present()

    def _on_export_format_chosen(self, dialog, response):
        if response not in ("csv", "json"):
            return
        self._export_fmt = response
        fd = Gtk.FileDialog()
        fd.set_initial_name(f"fedora-l10n.{response}")
        fd.save(self, None, self._on_export_save)

    def _on_export_save(self, dialog, result):
        try:
            path = dialog.save_finish(result).get_path()
        except Exception:
            return
        data = [{"project": p, "translated_percent": pct}
                for p, pct in self._projects]
        if not data:
            return
        if self._export_fmt == "csv":
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=data[0].keys())
                w.writeheader()
                w.writerows(data)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _on_lang_changed(self, entry):
        new_lang = entry.get_text().strip()
        if new_lang and new_lang != self._lang:
            self._lang = new_lang
            clear_cache()
            self._load_projects()

    def _on_project_activated(self, listbox, row):
        if not isinstance(row, ProjectRow):
            return
        slug = row.slug
        self._back_btn.set_visible(True)
        self.set_title(row.project_data.get("name", slug))
        self._load_components(slug)

    def _load_components(self, slug):
        self._stack.set_visible_child_name("loading")
        self._spinner.start()
        self._status_label.set_text(_("Loading components…"))

        def worker():
            try:
                components = get_components(slug)
                enriched = []
                for i, comp in enumerate(components):
                    comp_slug = comp.get("slug", "")
                    try:
                        stats = get_component_statistics(slug, comp_slug, self._lang)
                        pct = stats.get("translated_percent", 0) if stats else 0
                    except Exception:
                        pct = 0
                    enriched.append((comp, pct))
                GLib.idle_add(self._populate_components, enriched, slug)
            except Exception as e:
                GLib.idle_add(self._show_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_components(self, enriched, project_slug):
        self._spinner.stop()
        # Clear
        while True:
            row = self._component_list.get_row_at_index(0)
            if row is None:
                break
            self._component_list.remove(row)

        for comp, pct in sorted(enriched, key=lambda x: x[1], reverse=True):
            name = comp.get("name", comp.get("slug", ""))
            slug = comp.get("slug", "")
            self._component_list.append(ComponentRow(name, slug, pct, project_slug))

        self._stack.set_visible_child_name("components")

    def _on_heatmap_toggled(self, btn):
        self._heatmap_mode = btn.get_active()
        if self._heatmap_mode and self._projects:
            self._rebuild_heatmap()
            self._stack.set_visible_child_name("heatmap")
        elif self._projects:
            self._stack.set_visible_child_name("projects")

    def _rebuild_heatmap(self):
        while True:
            child = self._heatmap_flow.get_first_child()
            if child is None:
                break
            self._heatmap_flow.remove(child)

        ft = self._filter_text.lower()
        for proj, pct in sorted(self._projects, key=lambda x: x[1], reverse=True):
            name = proj.get("name", proj.get("slug", ""))
            slug = proj.get("slug", "")
            if ft and ft not in name.lower() and ft not in slug.lower():
                continue
            cell = _create_heatmap_cell(name, pct, tooltip=slug)
            gesture = Gtk.GestureClick()
            gesture.connect("released", lambda g, n, x, y, s=slug: self._load_components(s))
            cell.add_controller(gesture)
            cell.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            self._heatmap_flow.append(cell)

    def _on_back(self, btn):
        self._back_btn.set_visible(False)
        self.set_title(_("Fedora Translation Status"))
        if self._heatmap_mode:
            self._stack.set_visible_child_name("heatmap")
        else:
            self._stack.set_visible_child_name("projects")

    def _show_error(self, msg):
        self._spinner.stop()
        self._status_label.set_text(_("Error: {msg}").format(msg=msg))

    def _on_api_key(self, action, param):
        """Show dialog to enter Weblate API key."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Weblate API Key"),
            body=_(
                "A Weblate API key is needed to fetch translation statistics.\n\n"
                "Get your key from:\nhttps://translate.fedoraproject.org/accounts/profile/#api\n\n"
                "The key is stored securely in GNOME Keyring."
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_placeholder_text(_("Paste your API key here…"))
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        dialog.set_extra_child(entry)

        def on_response(d, response):
            if response == "save":
                key = entry.get_text().strip()
                if key:
                    save_api_key(key)
                    clear_cache()
                    self._load_projects()
            d.close()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_clear_cache(self, action, param):
        clear_cache()
        self._load_projects()

    def _on_toggle_notifications(self, action, param):
        config = _load_notify_config()
        config["enabled"] = not config.get("enabled", False)
        _save_notify_config(config)
        state = _("enabled") if config["enabled"] else _("disabled")
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Notifications"),
            body=_("Desktop notifications are now {state}.").format(state=state),
        )
        dialog.add_response("ok", _("OK"))
        dialog.present()

    def _on_about(self, action, param):
        about = Adw.AboutWindow(
            application_name=_("Fedora Translation Status"),
            application_icon="fedora-l10n",
            version=__version__,
            developer_name="Daniel Nylander",
            developers=["Daniel Nylander <daniel@danielnylander.se>"],
            copyright="© 2026 Daniel Nylander",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/yeager/fedora-l10n",
            issue_url="https://github.com/yeager/fedora-l10n/issues",
            translate_url="https://app.transifex.com/danielnylander/fedora-l10n/",
            transient_for=self,
            comments=_("View Fedora translation status from Weblate"),
            translator_credits="Daniel Nylander <daniel@danielnylander.se>",
        )
        # Copy system info button
        copy_btn = Gtk.Button(label=_("Copy System Info"))
        copy_btn.connect("clicked", lambda b: Gdk.Display.get_default().get_clipboard().set(_get_system_info()))
        copy_btn.set_halign(Gtk.Align.CENTER)
        copy_btn.set_margin_top(12)
        about.set_debug_info(_get_system_info())
        about.set_debug_info_filename("fedora-l10n-debug.txt")
        about.present()



    def _on_theme_toggle(self, _btn):
        sm = Adw.StyleManager.get_default()
        if sm.get_color_scheme() == Adw.ColorScheme.FORCE_DARK:
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            self._theme_btn.set_icon_name("weather-clear-night-symbolic")
        else:
            sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self._theme_btn.set_icon_name("weather-clear-symbolic")

    def _update_status_bar(self):
        self._status_bar.set_text("Last updated: " + _dt_now.now().strftime("%Y-%m-%d %H:%M"))


class FedoraL10nApp(Adw.Application):
    """Main application class."""

    def __init__(self):
        super().__init__(application_id=__app_id__)
        self._first_run_done = False
        if HAS_NOTIFY:
            _Notify.init(_NOTIFY_APP)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("app.refresh", ["F5"])
        self.set_accels_for_action("app.shortcuts", ["<Control>slash"])
        for n, cb in [("quit", lambda *_: self.quit()),
                      ("refresh", lambda *_: self._do_refresh()),
                      ("shortcuts", self._show_shortcuts_window),
                      ("export", lambda *_: self.get_active_window() and self.get_active_window()._on_export_clicked())]:
            a = Gio.SimpleAction.new(n, None); a.connect("activate", cb); self.add_action(a)
        self.set_accels_for_action("app.export", ["<Control>e"])

    def _do_refresh(self):
        w = self.get_active_window()
        if w and hasattr(w, '_load_data'): w._load_data()
        elif w and hasattr(w, '_on_refresh'): w._on_refresh(None)

    def _show_shortcuts_window(self, *_args):
        win = Gtk.ShortcutsWindow(transient_for=self.get_active_window(), modal=True)
        section = Gtk.ShortcutsSection(visible=True, max_height=10)
        group = Gtk.ShortcutsGroup(visible=True, title="General")
        for accel, title in [("<Control>q", "Quit"), ("F5", "Refresh"), ("<Control>slash", "Keyboard shortcuts")]:
            s = Gtk.ShortcutsShortcut(visible=True, accelerator=accel, title=title)
            group.append(s)
        section.append(group)
        win.add_child(section)
        win.present()

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = FedoraL10nWindow(self)
            if not self._first_run_done:
                self._first_run_done = True
                self._show_welcome(win)
        win.present()

    def _show_welcome(self, win):
        if not has_api_key():
            dialog = Adw.MessageDialog(
                transient_for=win,
                heading=_("Weblate API Key Required"),
                body=_(
                    "This app needs a Weblate API key to fetch translation statistics "
                    "from translate.fedoraproject.org.\n\n"
                    "Without a key, all percentages will show 0%.\n\n"
                    "Get your key from:\nhttps://translate.fedoraproject.org/accounts/profile/#api"
                ),
            )
            dialog.add_response("later", _("Later"))
            dialog.add_response("enter", _("Enter Key…"))
            dialog.set_response_appearance("enter", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("enter")

            def on_response(d, response):
                d.close()
                if response == "enter":
                    win._on_api_key(None, None)

            dialog.connect("response", on_response)
            dialog.present()
            return

        config_dir = GLib.get_user_config_dir()
        flag = f"{config_dir}/fedora-l10n/.welcome-done"
        if not GLib.file_test(flag, GLib.FileTest.EXISTS):
            dialog = Adw.MessageDialog(
                transient_for=win,
                heading=_("Welcome to Fedora Translation Status!"),
                body=_(
                    "This app shows the translation progress of Fedora projects "
                    "via the Weblate API.\n\n"
                    "Your system language is auto-detected, but you can change it "
                    "using the language field.\n\n"
                    "Click on a project to see its components."
                ),
            )
            dialog.add_response("ok", _("Get Started"))
            dialog.set_default_response("ok")
            dialog.connect("response", lambda d, r: d.close())
            dialog.present()
            # Mark as done
            import os
from datetime import datetime as _dt_now
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            with open(flag, "w") as f:
                f.write("1")


def main():
    app = FedoraL10nApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    main()
