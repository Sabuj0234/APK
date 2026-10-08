"""
Meter Reader (Android) - Kivy front-end for the DLMS/TCP core.

Flow: Connect screen -> Objects list (search) -> Object detail
(attributes, or Profile Generic buffer with CSV export) -> Log screen.
"""
import csv
import json
import os
import threading
import traceback
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.utils import escape_markup

import dlms_core as core
from gurux_dlms.enums import ObjectType

KV = r"""
#:import dp kivy.metrics.dp

<ObjRow>:
    size_hint_y: None
    height: dp(62)
    halign: 'left'
    valign: 'middle'
    text_size: self.width - dp(20), self.height
    background_normal: ''
    background_color: 0.11, 0.13, 0.19, 1
    on_release: app.open_object(self.idx)

<Field@TextInput>:
    multiline: False
    size_hint_y: None
    height: dp(44)
    write_tab: False

<Lbl@Label>:
    size_hint_y: None
    height: dp(22)
    halign: 'left'
    text_size: self.size
    color: 0.6, 0.65, 0.72, 1

<ConnectScreen>:
    name: 'connect'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(6)
        canvas.before:
            Color:
                rgba: 0.05, 0.07, 0.09, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: 'METER READER  -  TCP'
            bold: True
            font_size: '20sp'
            size_hint_y: None
            height: dp(44)
        ScrollView:
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(4)
                Lbl:
                    text: 'Meter IP (IPv4 / IPv6)'
                Field:
                    id: ip
                Lbl:
                    text: 'Port'
                Field:
                    id: port
                    input_filter: 'int'
                Lbl:
                    text: 'Association'
                Spinner:
                    id: assoc
                    values: ['PC', 'MR', 'US', 'PUSH', 'IHD']
                    size_hint_y: None
                    height: dp(44)
                Lbl:
                    text: 'HLS key (hex)'
                Field:
                    id: hlskey
                Lbl:
                    text: 'System title (hex)'
                Field:
                    id: systitle
                Lbl:
                    text: 'Authentication key (hex)'
                Field:
                    id: authkey
                Lbl:
                    text: 'Block cipher key (hex)'
                Field:
                    id: blockkey
        Label:
            id: status
            text: 'Not connected'
            size_hint_y: None
            height: dp(40)
            text_size: self.size
            halign: 'center'
            valign: 'middle'
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            spacing: dp(8)
            Button:
                text: 'Connect + Read Objects'
                on_release: app.connect()
            Button:
                text: 'Log'
                size_hint_x: 0.3
                on_release: app.goto('log')

<ObjectsScreen>:
    name: 'objects'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            Button:
                text: '<'
                size_hint_x: None
                width: dp(44)
                on_release: app.goto('connect')
            TextInput:
                id: search
                hint_text: 'Search name / OBIS'
                multiline: False
                on_text: app.filter_objects(self.text)
            Button:
                text: 'Log'
                size_hint_x: None
                width: dp(56)
                on_release: app.goto('log')
        Label:
            id: count
            size_hint_y: None
            height: dp(22)
            text: ''
        RecycleView:
            id: rv
            viewclass: 'ObjRow'
            RecycleBoxLayout:
                default_size: None, dp(62)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
                spacing: dp(2)

<DetailScreen>:
    name: 'detail'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            Button:
                text: '<'
                size_hint_x: None
                width: dp(44)
                on_release: app.goto('objects')
            Label:
                id: title
                text: ''
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Button:
                text: 'Read'
                size_hint_x: None
                width: dp(80)
                on_release: app.read_attributes()
        BoxLayout:
            id: profile_box
            size_hint_y: None
            height: 0
            opacity: 0
            disabled: True
            spacing: dp(6)
            Spinner:
                id: pmode
                text: 'Last N entries'
                values: ['Last N entries', 'Last N days', 'Whole buffer']
            TextInput:
                id: pn
                text: '10'
                multiline: False
                input_filter: 'int'
                size_hint_x: None
                width: dp(60)
            Button:
                text: 'Read buffer'
                on_release: app.read_profile()
            Button:
                text: 'CSV'
                size_hint_x: None
                width: dp(60)
                on_release: app.export_csv()
        BoxLayout:
            id: write_box
            size_hint_y: None
            height: 0
            opacity: 0
            disabled: True
            orientation: 'vertical'
            spacing: dp(6)
            BoxLayout:
                size_hint_y: None
                height: dp(42)
                spacing: dp(6)
                Spinner:
                    id: write_attr
                    size_hint_x: 0.42
                    text: 'Attribute'
                    values: []
                    on_text: app.update_write_type()
                TextInput:
                    id: write_value
                    hint_text: 'Value'
                    multiline: False
                Button:
                    text: 'Write'
                    size_hint_x: None
                    width: dp(76)
                    on_release: app.confirm_write()
            Label:
                id: write_type
                size_hint_y: None
                height: dp(20)
                text: 'DLMS type: unavailable'
                halign: 'left'
                text_size: self.size
        Label:
            id: dstatus
            size_hint_y: None
            height: dp(22)
            text: ''
        ScrollView:
            Label:
                id: out
                markup: True
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
                padding: dp(6), dp(6)

<LogScreen>:
    name: 'log'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            Button:
                text: '<'
                size_hint_x: None
                width: dp(44)
                on_release: app.goto(app.prev_screen)
            Button:
                text: 'Clear'
                on_release: app.clear_log()
        ScrollView:
            Label:
                id: logtxt
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
                font_size: '11sp'
"""


class ObjRow(Button):
    idx = NumericProperty(0)


class ConnectScreen(Screen):
    pass


class ObjectsScreen(Screen):
    pass


class DetailScreen(Screen):
    pass


class LogScreen(Screen):
    pass


MAX_PROFILE_ROWS_SHOWN = 60   # on-screen limit; CSV export always has all rows
MAX_LOG_LINES = 150


class MeterReaderApp(App):
    title = "Meter Reader"
    prev_screen = "connect"

    # ─── lifecycle ────────────────────────────────────────────────────────
    def build(self):
        self.objects = []        # all objects from the meter
        self.shown = []          # filtered view
        self.current = None
        self.attr_lines = {}
        self.profile = None      # (cols, rows) of last read
        self.log_lines = []
        self.busy = False
        root = Builder.load_string(KV)
        from kivy.uix.screenmanager import ScreenManager
        sm = ScreenManager()
        for cls in (ConnectScreen, ObjectsScreen, DetailScreen, LogScreen):
            sm.add_widget(cls())
        self.sm = sm
        self._load_settings()
        return sm

    @property
    def _settings_path(self):
        return os.path.join(self.user_data_dir, "settings.json")

    def _load_settings(self):
        d = core.MeterConfig().__dict__.copy()
        d["host"] = "2401:4900:D0DF:8A78:0000:0000:0000:0002"
        try:
            with open(self._settings_path, "r") as f:
                d.update(json.load(f))
        except Exception:
            pass
        s = self.sm.get_screen("connect").ids
        s.ip.text = str(d["host"])
        s.port.text = str(d["port"])
        s.assoc.text = d["association"]
        s.hlskey.text = d["hls_key"]
        s.systitle.text = d["system_title"]
        s.authkey.text = d["auth_key"]
        s.blockkey.text = d["block_cipher_key"]

    def _save_settings(self, cfg):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self._settings_path, "w") as f:
                json.dump(cfg.__dict__, f)
        except Exception as e:
            self.log(f"Could not save settings: {e}")

    def on_pause(self):
        return True   # keep app alive when switching apps

    # ─── helpers ──────────────────────────────────────────────────────────
    def goto(self, name):
        if name == "log":
            self.prev_screen = self.sm.current if self.sm.current != "log" else self.prev_screen
            self._refresh_log()
        self.sm.current = name

    def log(self, msg):
        line = f"{datetime.now():%H:%M:%S} {msg}"
        self.log_lines.append(line)
        del self.log_lines[:-MAX_LOG_LINES]
        Clock.schedule_once(lambda dt: self._refresh_log(), 0)

    def _refresh_log(self):
        self.sm.get_screen("log").ids.logtxt.text = "\n".join(self.log_lines)

    def clear_log(self):
        self.log_lines = []
        self._refresh_log()

    def _ui(self, fn, *a):
        Clock.schedule_once(lambda dt: fn(*a), 0)

    def _status(self, text):
        self.sm.get_screen("connect").ids.status.text = text

    def _cfg(self):
        s = self.sm.get_screen("connect").ids
        for name in ("hlskey", "systitle", "authkey", "blockkey"):
            bytes.fromhex(s[name].text.strip())      # validate hex early
        return core.MeterConfig(
            host=s.ip.text.strip(),
            port=int(s.port.text or 4059),
            association=s.assoc.text,
            hls_key=s.hlskey.text.strip(),
            system_title=s.systitle.text.strip(),
            auth_key=s.authkey.text.strip(),
            block_cipher_key=s.blockkey.text.strip(),
        )

    def _worker(self, fn):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                fn()
            except Exception as e:
                self.log("ERROR: " + traceback.format_exc())
                self._ui(self._status, f"Error: {e}")
                self._ui(self._dstatus, f"Error: {e}")
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    # ─── connect + object list ───────────────────────────────────────────
    def connect(self):
        try:
            cfg = self._cfg()
        except Exception as e:
            self._status(f"Check inputs (hex keys / port): {e}")
            return
        self._save_settings(cfg)
        self._status("Connecting...")

        def job():
            with core.MeterSession(cfg, self.log) as s:
                objs = s.read_object_list()
            objs.sort(key=lambda o: (int(o.objectType), o.logicalName))
            self.objects = objs
            self.log(f"Found {len(objs)} objects")
            self._ui(self._status, f"Connected - {len(objs)} objects")
            self._ui(self._show_objects)
        self._worker(job)

    def _show_objects(self):
        self.sm.get_screen("objects").ids.search.text = ""
        self.filter_objects("")
        self.sm.current = "objects"

    def filter_objects(self, text):
        t = (text or "").lower().strip()
        self.shown = [
            o for o in self.objects
            if not t or t in o.logicalName
            or t in core.obis_name(o.logicalName).lower()
            or t in core.object_type_name(o).lower()
        ]
        ids = self.sm.get_screen("objects").ids
        ids.count.text = f"{len(self.shown)} / {len(self.objects)} objects"
        ids.rv.data = [
            {"idx": i,
             "text": f"{core.obis_name(o.logicalName)}\n"
                     f"{o.logicalName}  -  {core.object_type_name(o)}"}
            for i, o in enumerate(self.shown)
        ]

    # ─── object detail ───────────────────────────────────────────────────
    def open_object(self, idx):
        obj = self.shown[idx]
        self.current = obj
        self.attr_lines = {}
        self.profile = None
        d = self.sm.get_screen("detail").ids
        d.title.text = f"{core.obis_name(obj.logicalName)}\n{obj.logicalName}"
        d.write_box.height = 0
        d.write_box.opacity = 0
        d.write_box.disabled = True
        d.write_value.text = ""
        is_profile = obj.objectType == ObjectType.PROFILE_GENERIC
        d.profile_box.height = 44 if is_profile else 0
        d.profile_box.opacity = 1 if is_profile else 0
        d.profile_box.disabled = not is_profile
        d.dstatus.text = ""
        d.out.text = ""
        self.sm.current = "detail"
        self.read_attributes()

    def _dstatus(self, text):
        self.sm.get_screen("detail").ids.dstatus.text = text

    def _render_attrs(self):
        lines = []
        for idx, name in core.attributes_for(self.current):
            if idx in self.attr_lines:
                lines.append(f"[b]{idx}. {escape_markup(name)}[/b]\n"
                             f"{escape_markup(self.attr_lines[idx])}\n")
        self.sm.get_screen("detail").ids.out.text = "\n".join(lines)

    def _configure_write(self, obj):
        if self.current is not obj:
            return
        ids = self.sm.get_screen("detail").ids
        options = core.writable_scalar_attributes(obj)
        ids.write_attr.values = [f"{index}: {name}" for index, name in options]
        ids.write_attr.text = ids.write_attr.values[0] if options else "Attribute"
        ids.write_box.height = dp(68) if options else 0
        ids.write_box.opacity = 1 if options else 0
        ids.write_box.disabled = not options
        self.update_write_type()

    def update_write_type(self):
        ids = self.sm.get_screen("detail").ids
        try:
            index = int(ids.write_attr.text.split(":", 1)[0])
            data_type = self.current.getDataType(index)
        except (AttributeError, TypeError, ValueError):
            ids.write_type.text = "DLMS type: unavailable"
            return
        ids.write_type.text = f"DLMS type read from meter: {data_type.name}"

    def confirm_write(self):
        ids = self.sm.get_screen("detail").ids
        try:
            index_text, name = ids.write_attr.text.split(": ", 1)
            index = int(index_text)
            value = ids.write_value.text
            data_type = self.current.getDataType(index)
            if not value and data_type not in (
                core.DataType.STRING, core.DataType.STRING_UTF8
            ):
                raise ValueError("Enter a value to write")
        except Exception as e:
            self._dstatus(f"Choose an attribute and enter a valid value: {e}")
            return

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        content.add_widget(
            Label(text=f"Write {value!r} as {data_type.name} to {name}?")
        )
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel = Button(text="Cancel")
        confirm = Button(text="Confirm")
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(actions)
        popup = Popup(
            title="Confirm meter write",
            content=content,
            size_hint=(0.9, 0.32),
            auto_dismiss=False,
        )
        cancel.bind(on_release=lambda *_: popup.dismiss())
        confirm.bind(
            on_release=lambda *_: self._write_attribute(popup, index, name, value)
        )
        popup.open()

    def _write_attribute(self, popup, index, name, value):
        popup.dismiss()
        obj = self.current
        try:
            cfg = self._cfg()
        except Exception as e:
            self._dstatus(f"Check inputs: {e}")
            return
        self._dstatus(f"Writing {name}...")

        def job():
            with core.MeterSession(cfg, self.log) as session:
                written = session.write_attribute(obj, index, value)
            if self.current is obj:
                self.attr_lines[index] = written
                self._ui(self._render_attrs)
            self._ui(self._dstatus, f"Write accepted for {name}")
            self.log(f"Wrote attribute {index} ({name}) = {written}")

        self._worker(job)

    def read_attributes(self):
        obj = self.current
        if obj is None:
            return
        try:
            cfg = self._cfg()
        except Exception as e:
            self._dstatus(f"Check inputs: {e}")
            return
        self._dstatus("Reading...")

        def job():
            with core.MeterSession(cfg, self.log) as s:
                for idx, name in core.attributes_for(obj):
                    if obj.objectType == ObjectType.PROFILE_GENERIC and idx == 2:
                        self.attr_lines[idx] = "(use 'Read buffer')"
                    else:
                        try:
                            self.attr_lines[idx] = s.read_attribute(obj, idx)
                        except Exception as e:
                            self.attr_lines[idx] = f"Error: {e}"
                    self._ui(self._render_attrs)
                    self._ui(self._configure_write, obj)
            self._ui(self._dstatus, "Done")
        self._worker(job)

    # ─── profile generic ─────────────────────────────────────────────────
    def read_profile(self):
        obj = self.current
        if obj is None or obj.objectType != ObjectType.PROFILE_GENERIC:
            return
        d = self.sm.get_screen("detail").ids
        try:
            cfg = self._cfg()
            n = max(1, int(d.pn.text or 1))
        except Exception as e:
            self._dstatus(f"Check inputs: {e}")
            return
        mode = {"Last N entries": "last", "Last N days": "days"}.get(d.pmode.text, "all")
        self._dstatus("Reading buffer...")

        def job():
            with core.MeterSession(cfg, self.log) as s:
                cols, rows = s.read_profile(obj, mode=mode, count=n, days=n)
            self.profile = (cols, rows)
            self.log(f"Profile: {len(rows)} rows, {len(cols)} columns")
            self._ui(self._render_profile)
        self._worker(job)

    def _render_profile(self):
        cols, rows = self.profile
        out = []
        for i, row in enumerate(rows[:MAX_PROFILE_ROWS_SHOWN], 1):
            parts = []
            for ci, v in enumerate(row):
                c = cols[ci] if ci < len(cols) else f"Col{ci}"
                parts.append(f"[color=88aaff]{escape_markup(c)}[/color]: {escape_markup(v)}")
            out.append(f"[b]#{i}[/b]\n" + "\n".join(parts) + "\n")
        more = len(rows) - MAX_PROFILE_ROWS_SHOWN
        if more > 0:
            out.append(f"... {more} more rows (use CSV to get all)")
        d = self.sm.get_screen("detail").ids
        d.out.text = "\n".join(out) or "(no rows)"
        d.dstatus.text = f"{len(rows)} rows"

    def export_csv(self):
        if not self.profile:
            self._dstatus("Read the buffer first")
            return
        cols, rows = self.profile
        name = f"{self.current.logicalName.replace('.', '_')}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            path = os.path.join(self.user_data_dir, name)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["#"] + cols)
                for i, r in enumerate(rows, 1):
                    w.writerow([i] + r)
            self._dstatus(f"Saved: {path}")
            self.log(f"CSV saved: {path}")
        except Exception as e:
            self._dstatus(f"CSV failed: {e}")


if __name__ == "__main__":
    MeterReaderApp().run()
