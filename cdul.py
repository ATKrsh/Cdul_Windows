# cdul.py
# Cdul — Minimal Telemetry Widget (Pure Link Source & Link Sink)
# Always-on-top translucent circular widget connecting hardware telemetry to visual indicators.

import sys
import os
import io
import time
import math
import json
import collections
import threading
import subprocess
import winreg
import ctypes
import ctypes.wintypes

# Force stdout/stderr to UTF-8
class _DummyWriter:
    def write(self, *a, **k): pass
    def flush(self, *a, **k): pass

if sys.stdout is None:
    sys.stdout = _DummyWriter()
else:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

if sys.stderr is None:
    sys.stderr = _DummyWriter()
else:
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# Single Instance Guarantee for Cdul
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

def kill_previous_instances():
    import psutil
    current_pid = os.getpid()
    if getattr(sys, 'frozen', False):
        exe_name = os.path.basename(sys.executable)
        subprocess.run(f'taskkill /F /FI "PID ne {current_pid}" /IM "{exe_name}"', shell=True, capture_output=True)
        subprocess.run(f'taskkill /F /FI "PID ne {current_pid}" /IM "Cdul*"', shell=True, capture_output=True)
    else:
        subprocess.run(f'wmic process where "name like \'%cdul%\' and ProcessId != {current_pid}" call terminate', shell=True, capture_output=True)

    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                pid = proc.info['pid']
                if pid == current_pid: continue
                pname = (proc.info['name'] or '').lower()
                exe_path = (proc.info['exe'] or '').lower()
                cmd = proc.info['cmdline'] or []
                cmd_str = ' '.join(cmd).lower()
                if 'cdul' in pname or 'cdul' in exe_path or 'cdul.py' in cmd_str:
                    try: proc.kill()
                    except Exception: subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    except Exception: pass

# Crash Logger
LOG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Cdul", "Logs")
os.makedirs(LOG_DIR, exist_ok=True)
CRASH_LOG_FILE = os.path.join(LOG_DIR, "cdul_crash_report.txt")

def log_crash_report(exc_type, exc_value, exc_tb):
    import traceback, datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = f"Time: {now_str}\nError: {exc_type.__name__}: {exc_value}\nTraceback:\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(CRASH_LOG_FILE, "w", encoding="utf-8") as f: f.write(report)
    except Exception: pass

sys.excepthook = log_crash_report

try:
    _con = ctypes.windll.kernel32.GetConsoleWindow()
    if _con: ctypes.windll.user32.ShowWindow(_con, 0)
except Exception: pass

kill_previous_instances()

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSystemTrayIcon,
    QMenu, QAction, QSlider, QWidgetAction, QLabel, QActionGroup,
    QDialog, QGridLayout, QComboBox, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt, QPoint, QPointF, QRectF, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QIcon, QPixmap, QCursor, QRadialGradient

import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    HAS_NVML = True
except Exception:
    HAS_NVML = False

# Paths & Config
APP_DATA_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), "Cdul")
os.makedirs(APP_DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Cdul"

DEFAULT_CONFIG = {
    "opacity": 0.9,
    "glow_opacity": 0.9,
    "glow_size_pct": 50,
    "size_pct": 50,
    "hue": 190,
    "telemetry_source": "cpu_usage", # Link Source
    "telemetry_target": "app_size",  # Link Sink
    "hdd_drive": "All",
    "hdd_mode": "both",
    "net_mode": "both",
    "gpu_choice": "gpu0",
    "always_on_top": True,
    "lock_position": False,
    "clickthrough": False,
    "start_with_windows": False,
    "pos_x": -1,
    "pos_y": -1
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg.update(json.load(f))
        except Exception: pass
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception: pass

def set_startup(enable):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            exe_path = f'"{sys.executable}"' if not getattr(sys, 'frozen', False) else f'"{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
        else:
            try: winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError: pass
        winreg.CloseKey(key)
    except Exception as e: print("Registry error:", e)

class PersistentMenu(QMenu):
    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if action and action.isCheckable():
            action.trigger()
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

# Win32 Flags
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE  = 0x08000080
WS_EX_TOOLWINDOW  = 0x00000080
GetWindowLongW = ctypes.windll.user32.GetWindowLongW
SetWindowLongW = ctypes.windll.user32.SetWindowLongW

# Telemetry Hardware Monitor
class TelemetryMonitor(threading.Thread):
    def __init__(self, widget_app):
        super().__init__(daemon=True)
        self.app = widget_app
        self.breath_phase = 0.0
        self.last_net_bytes = psutil.net_io_counters()
        self.last_net_time  = time.time()
        self.last_disk_bytes = psutil.disk_io_counters()
        self.last_disk_time  = time.time()

    def get_sample(self):
        src = self.app.config.get("telemetry_source", "cpu_usage")
        val = 0.0

        if src == "none": return 0.0
        elif src == "breathing":
            self.breath_phase = (self.breath_phase + 0.05) % (2.0 * math.pi)
            return (math.sin(self.breath_phase) + 1.0) / 2.0
        elif src == "cpu_freq":
            try:
                freq = psutil.cpu_freq()
                if freq and freq.max > 0: val = min(1.0, max(0.0, (freq.current - freq.min) / (freq.max - freq.min)))
            except Exception: pass
        elif src == "cpu_usage":
            try: val = psutil.cpu_percent(interval=None) / 100.0
            except Exception: pass
        elif src == "hdd":
            try:
                now = time.time(); dt = max(0.001, now - self.last_disk_time)
                cur_disk = psutil.disk_io_counters()
                if cur_disk and self.last_disk_bytes:
                    r = cur_disk.read_bytes - self.last_disk_bytes.read_bytes
                    w = cur_disk.write_bytes - self.last_disk_bytes.write_bytes
                    m = self.app.config.get("hdd_mode", "both")
                    tot = r if m == "read" else (w if m == "write" else r + w)
                    val = min(1.0, (tot / dt) / (100.0 * 1024.0 * 1024.0))
                self.last_disk_bytes = cur_disk; self.last_disk_time = now
            except Exception: pass
        elif src == "memory":
            try: val = psutil.virtual_memory().percent / 100.0
            except Exception: pass
        elif src == "ethernet":
            try:
                now = time.time(); dt = max(0.001, now - self.last_net_time)
                cur_net = psutil.net_io_counters()
                if cur_net and self.last_net_bytes:
                    s = cur_net.bytes_sent - self.last_net_bytes.bytes_sent
                    r = cur_net.bytes_recv - self.last_net_bytes.bytes_recv
                    m = self.app.config.get("net_mode", "both")
                    tot = s if m == "upload" else (r if m == "download" else s + r)
                    val = min(1.0, (tot / dt) / (10.0 * 1024.0 * 1024.0))
                self.last_net_bytes = cur_net; self.last_net_time = now
            except Exception: pass
        elif src == "gpu" and HAS_NVML:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                val = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu / 100.0
            except Exception: pass
        elif src == "power":
            try:
                b = psutil.sensors_battery()
                val = (b.percent / 100.0) if b else 1.0
            except Exception: pass
        elif src == "keyboard": val = 0.5
        return min(1.0, max(0.0, val))

    def run(self):
        while True:
            try:
                sample = self.get_sample()
                self.app.telemetry_val += (sample - self.app.telemetry_val) * 0.15
            except Exception: pass
            time.sleep(0.1)

# Telemetry Dashboard Window
class DashboardWindow(QDialog):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowTitle("Cdul — Link Telemetry Controller")
        self.resize(650, 380)
        self.setStyleSheet("""
            QDialog { background-color: #121212; color: #E0E0E0; }
            QGroupBox { border: 1px solid #333; border-radius: 8px; margin-top: 20px; font-weight: bold; color: #00E5FF; padding: 15px 10px 10px 10px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; }
            QLabel { color: #CCCCCC; font-weight: bold; }
            QCheckBox { color: #CCCCCC; spacing: 10px; font-weight: bold; }
            QCheckBox::indicator { width: 40px; height: 20px; border-radius: 10px; }
            QCheckBox::indicator:unchecked { background-color: #333; }
            QCheckBox::indicator:checked { background-color: #00E5FF; }
            QSlider::groove:horizontal { height: 6px; background: #333; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00E5FF; width: 14px; margin: -4px 0; border-radius: 7px; }
            QComboBox { background-color: #1E1E1E; color: #FFF; border: 1px solid #333; border-radius: 4px; padding: 4px; font-weight: bold; }
        """)

        main_layout = QVBoxLayout(self)
        grid = QGridLayout()
        main_layout.addLayout(grid)

        def add_combo(layout, label, items, cur_val, callback):
            h = QHBoxLayout()
            h.addWidget(QLabel(label))
            cb = QComboBox()
            for text, data in items: cb.addItem(text, data)
            idx = cb.findData(cur_val)
            if idx >= 0: cb.setCurrentIndex(idx)
            cb.currentIndexChanged.connect(lambda i: callback(cb.itemData(i)))
            h.addWidget(cb)
            layout.addLayout(h)

        def add_slider(layout, label, min_v, max_v, cur_val, callback):
            h = QHBoxLayout()
            h.addWidget(QLabel(label))
            sl = QSlider(Qt.Horizontal)
            sl.setRange(min_v, max_v); sl.setValue(cur_val)
            val_lbl = QLabel(str(cur_val))
            def on_change(v): val_lbl.setText(str(v)); callback(v)
            sl.valueChanged.connect(on_change)
            h.addWidget(sl); h.addWidget(val_lbl)
            layout.addLayout(h)

        # --- TELEMETRY LINKS ---
        v1 = QVBoxLayout()
        add_combo(v1, "Link Source (Input Channel)", [
            ("0. None", "none"), ("1. Breathing Sine", "breathing"), ("2. CPU Frequency", "cpu_freq"),
            ("3. CPU Usage", "cpu_usage"), ("4. HDD Activity", "hdd"), ("5. Memory Usage", "memory"),
            ("6. Ethernet Activity", "ethernet"), ("7. GPU Usage", "gpu"), ("8. Power Usage", "power")
        ], main_app.config.get("telemetry_source", "cpu_usage"), main_app._set_telemetry_source)

        add_combo(v1, "Link Sink (Visual Output Target)", [
            ("0. None", "none"), ("1. App Size", "app_size"), ("2. App Color (Red->Blue)", "app_color"),
            ("3. Glow Size", "glow_size"), ("4. Glow Color (Blue->Red)", "glow_color"),
            ("5. App Opacity", "app_opacity"), ("6. Glow Opacity", "glow_opacity"),
            ("7. Both Size", "app_glow_size"), ("8. Both Color", "app_glow_color"),
            ("9. Both Opacity", "app_glow_opacity")
        ], main_app.config.get("telemetry_target", "app_size"), main_app._set_telemetry_target)
        grp1 = QGroupBox("Link Telemetry Core"); grp1.setLayout(v1); grid.addWidget(grp1, 0, 0, 1, 2)

        # --- SLIDERS ---
        v2 = QVBoxLayout()
        add_slider(v2, "App Size %", 20, 200, main_app.config.get("size_pct", 50), main_app._on_size)
        add_slider(v2, "App Opacity %", 10, 100, int(main_app.config.get("opacity", 0.9)*100), main_app._on_opacity)
        add_slider(v2, "Glow Size %", 10, 100, main_app.config.get("glow_size_pct", 50), main_app._on_glow_size)
        add_slider(v2, "Glow Opacity %", 10, 100, int(main_app.config.get("glow_opacity", 0.9)*100), main_app._on_glow_opacity)
        add_slider(v2, "Color Hue °", 0, 360, main_app.config.get("hue", 190), main_app._on_hue)
        grp2 = QGroupBox("Base Visual Adjustments"); grp2.setLayout(v2); grid.addWidget(grp2, 1, 0, 1, 2)

# Cdul Button Orb
class CdulButton(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._p = parent
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._is_drag = False
        self._drag_pos = QPoint()

        t = QTimer(self); t.timeout.connect(self.update); t.start(25)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2.0; cy = self.height() / 2.0
        base_size = 32.0 + 56.0 * (self._p.config.get("size_pct", 50) / 100.0)
        t_target  = self._p.config.get("telemetry_target", "app_size")

        if t_target in ("app_size", "app_glow_size"):
            base_size += self._p.telemetry_val * 45.0

        outer_r = max(10.0, base_size * 0.464)

        app_op = self._p.config.get("opacity", 0.9)
        glow_op = self._p.config.get("glow_opacity", 0.9)

        if t_target in ("app_opacity", "app_glow_opacity"): app_op *= (0.2 + 0.8 * self._p.telemetry_val)
        if t_target in ("glow_opacity", "app_glow_opacity"): glow_op *= (0.2 + 0.8 * self._p.telemetry_val)

        glow_ext = 5.0 + 35.0 * (self._p.config.get("glow_size_pct", 50) / 100.0)
        if t_target in ("glow_size", "app_glow_size"): glow_ext += self._p.telemetry_val * 55.0

        glow_radius = outer_r + glow_ext
        glow_alpha = int(180 * glow_op)

        custom_h = self._p.config.get("hue", 190)
        h_glow = custom_h; h_app = custom_h

        if t_target in ("glow_color", "app_glow_color"): h_glow = int(200.0 * (1.0 - self._p.telemetry_val))
        if t_target in ("app_color", "app_glow_color"): h_app = int(200.0 * (1.0 - self._p.telemetry_val))

        # Base Glow
        radial = QRadialGradient(cx, cy, glow_radius)
        glow_col = QColor.fromHsv(h_glow, 255, 255, glow_alpha)
        radial.setColorAt(0.0, glow_col)
        radial.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(radial)); p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - glow_radius, cy - glow_radius, glow_radius * 2.0, glow_radius * 2.0))

        # Core Orb
        orb_col = QColor.fromHsv(h_app, 180, 55, int(220 * app_op))
        p.setBrush(QBrush(orb_col)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)

        # Center Label
        p.setPen(QPen(glow_col, 2.0))
        font = p.font(); font.setBold(True); font.setPixelSize(int(outer_r * 0.5))
        p.setFont(font)
        p.drawText(QRectF(cx - outer_r, cy - outer_r, outer_r * 2.0, outer_r * 2.0), Qt.AlignCenter, "CDUL")

        # Border
        p.setPen(QPen(QColor(0, 230, 255, int(220 * app_op)), 1.8)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)
        p.end()

    def mousePressEvent(self, event):
        pw = self._p
        if event.button() == Qt.LeftButton:
            if not pw.config.get("lock_position", False) and not pw.config.get("clickthrough", False):
                self._drag_pos = event.globalPos() - pw.frameGeometry().topLeft()
                self._is_drag = False
        event.accept()

    def mouseMoveEvent(self, event):
        pw = self._p
        if event.buttons() & Qt.LeftButton and not pw.config.get("lock_position", False) and not pw.config.get("clickthrough", False):
            diff = event.globalPos() - (pw.frameGeometry().topLeft() + self._drag_pos)
            if diff.manhattanLength() > 4: self._is_drag = True
            if self._is_drag:
                pw.move(event.globalPos() - self._drag_pos)
                pw.config["pos_x"] = pw.x(); pw.config["pos_y"] = pw.y()
                save_config(pw.config)
        event.accept()

    def mouseReleaseEvent(self, event):
        pw = self._p
        if event.button() == Qt.LeftButton:
            if not self._is_drag: pw.show_dashboard()
            self._is_drag = False
        event.accept()

# Container Widget
class CdulWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.SubWindow | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        px = QPixmap(32, 32); px.fill(Qt.transparent)
        painter = QPainter(px); painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(0, 210, 255), 2)); painter.setBrush(QBrush(QColor(18, 24, 38)))
        painter.drawEllipse(3, 3, 26, 26); painter.end()
        self.app_icon = QIcon(px); self.setWindowIcon(self.app_icon)

        self.telemetry_val = 0.0
        self.telemetry_mon = TelemetryMonitor(self)
        self.telemetry_mon.start()

        base_size = int(32 + 56 * (self.config.get("size_pct", 50) / 100.0))
        size_px = base_size + 280
        self.setFixedSize(size_px, size_px)

        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.button = CdulButton(self); layout.addWidget(self.button)

        screen_geo = QApplication.primaryScreen().geometry()
        def_x = self.config.get("pos_x", -1); def_y = self.config.get("pos_y", -1)
        if def_x < 0 or def_y < 0:
            def_x = screen_geo.width() - size_px - 50; def_y = screen_geo.height() - size_px - 100
        self.move(def_x, def_y)

        hwnd = int(self.winId()); ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
        flags = ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if self.config.get("clickthrough", False): flags |= WS_EX_TRANSPARENT
        SetWindowLongW(hwnd, GWL_EXSTYLE, flags)

        self._setup_tray()
        self.show()
        if self.config.get("always_on_top", True): self._enforce_always_on_top()

    def _enforce_always_on_top(self):
        if not self.config.get("always_on_top", True): return
        try:
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception: pass
        self.raise_()

    def _create_sub_menu(self, parent_menu, title):
        sub = PersistentMenu(title, self)
        sub.setStyleSheet(parent_menu.styleSheet())
        parent_menu.addMenu(sub)
        return sub

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.app_icon)
        self.tray_icon.setToolTip("Cdul — Link Telemetry Widget")

        SLIDER_SS = "QSlider::groove:horizontal { height:4px; background:#374151; border-radius:2px; } QSlider::sub-page:horizontal { background:#00d2ff; } QSlider::handle:horizontal { background:#fff; width:12px; height:12px; margin:-4px 0; border-radius:6px; }"
        self.tray_menu = PersistentMenu("", self)
        self.tray_menu.setStyleSheet("""
            QMenu { background-color:#1e222b; color:#e1e4ea; border:1px solid #3a4253; border-radius:8px; padding:6px; font-size:13px; }
            QMenu::item { padding:6px 24px 6px 12px; border-radius:4px; }
            QMenu::item:selected { background-color:#2c3444; color:#00d2ff; }
            QMenu::separator { height:1px; background:#3a4253; margin:4px 6px; }
        """)

        # Link Source Submenu
        source_menu = self._create_sub_menu(self.tray_menu, "📊 Link Source")
        cur_src = self.config.get("telemetry_source", "cpu_usage")
        src_grp = QActionGroup(self); src_grp.setExclusive(True)
        for label, code in [
            ("0. None", "none"), ("1. Breathing Sine", "breathing"), ("2. CPU Frequency", "cpu_freq"),
            ("3. CPU Usage", "cpu_usage"), ("4. HDD Activity", "hdd"), ("5. Memory Usage", "memory"),
            ("6. Ethernet Activity", "ethernet"), ("7. GPU Usage", "gpu"), ("8. Power Usage", "power")
        ]:
            act = QAction(label, self); act.setCheckable(True)
            src_grp.addAction(act)
            if cur_src == code: act.setChecked(True)
            act.triggered.connect(lambda _c, c=code: self._set_telemetry_source(c))
            source_menu.addAction(act)

        # Link Sink Submenu
        target_menu = self._create_sub_menu(self.tray_menu, "🔗 Link Sink")
        cur_tgt = self.config.get("telemetry_target", "app_size")
        tgt_grp = QActionGroup(self); tgt_grp.setExclusive(True)
        for label, code in [
            ("0. None", "none"), ("1. App Size", "app_size"), ("2. App Color", "app_color"),
            ("3. Glow Size", "glow_size"), ("4. Glow Color", "glow_color"), ("5. App Opacity", "app_opacity"),
            ("6. Glow Opacity", "glow_opacity"), ("7. Both Size", "app_glow_size"),
            ("8. Both Color", "app_glow_color"), ("9. Both Opacity", "app_glow_opacity")
        ]:
            act = QAction(label, self); act.setCheckable(True)
            tgt_grp.addAction(act)
            if cur_tgt == code: act.setChecked(True)
            act.triggered.connect(lambda _c, c=code: self._set_telemetry_target(c))
            target_menu.addAction(act)

        self.tray_menu.addSeparator()

        self.action_dashboard = QAction("🎛️ Telemetry Dashboard", self)
        self.action_dashboard.triggered.connect(self.show_dashboard)
        self.tray_menu.addAction(self.action_dashboard)

        self.action_ontop = QAction("Always on Top", self); self.action_ontop.setCheckable(True)
        self.action_ontop.setChecked(self.config.get("always_on_top", True))
        self.action_ontop.triggered.connect(self._toggle_ontop); self.tray_menu.addAction(self.action_ontop)

        self.action_lock = QAction("Lock Position", self); self.action_lock.setCheckable(True)
        self.action_lock.setChecked(self.config.get("lock_position", False))
        self.action_lock.triggered.connect(self._toggle_lock); self.tray_menu.addAction(self.action_lock)

        self.action_startup = QAction("Start with Windows", self); self.action_startup.setCheckable(True)
        self.action_startup.setChecked(self.config.get("start_with_windows", False))
        self.action_startup.triggered.connect(self._toggle_startup); self.tray_menu.addAction(self.action_startup)

        self.tray_menu.addSeparator()

        # Sliders
        for title, key, min_v, max_v, callback in [
            ("App Size", "size_pct", 20, 200, self._on_size),
            ("App Opacity", "opacity", 10, 100, self._on_opacity),
            ("Glow Size", "glow_size_pct", 10, 100, self._on_glow_size),
            ("Glow Opacity", "glow_opacity", 10, 100, self._on_glow_opacity),
            ("Color Hue", "hue", 0, 360, self._on_hue)
        ]:
            c = QWidget(); l = QHBoxLayout(c); l.setContentsMargins(12, 2, 12, 2)
            lbl = QLabel(f"{title}:"); lbl.setStyleSheet("color:#d1d5db; font-size:11px; font-weight:bold;")
            sl = QSlider(Qt.Horizontal); sl.setRange(min_v, max_v)
            val = int(self.config.get(key, 50)*100) if "opacity" in key else self.config.get(key, 50)
            sl.setValue(val); sl.setFixedWidth(90); sl.setStyleSheet(SLIDER_SS)
            sl.valueChanged.connect(callback)
            l.addWidget(lbl); l.addWidget(sl)
            wa = QWidgetAction(self); wa.setDefaultWidget(c); self.tray_menu.addAction(wa)

        self.tray_menu.addSeparator()
        qa = QAction("Quit Cdul", self); qa.triggered.connect(QApplication.quit)
        self.tray_menu.addAction(qa)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(lambda r: self.show_dashboard() if r == QSystemTrayIcon.Trigger else None)
        self.tray_icon.show()

    def _toggle_ontop(self, chk):
        self.config["always_on_top"] = chk; save_config(self.config); self._enforce_always_on_top()

    def _toggle_lock(self, chk):
        self.config["lock_position"] = chk; save_config(self.config); self.button.update()

    def _toggle_startup(self, chk):
        self.config["start_with_windows"] = chk; save_config(self.config); set_startup(chk)

    def _set_telemetry_source(self, src):
        self.config["telemetry_source"] = src; save_config(self.config); self.button.update()

    def _set_telemetry_target(self, tgt):
        self.config["telemetry_target"] = tgt; save_config(self.config); self.button.update()

    def _on_opacity(self, v): self.config["opacity"] = v / 100.0; save_config(self.config); self.button.update()
    def _on_glow_opacity(self, v): self.config["glow_opacity"] = v / 100.0; save_config(self.config); self.button.update()
    def _on_glow_size(self, v): self.config["glow_size_pct"] = v; save_config(self.config); self.button.update()
    def _on_hue(self, v): self.config["hue"] = v; save_config(self.config); self.button.update()
    def _on_size(self, v):
        self.config["size_pct"] = v; save_config(self.config)
        size_px = int(32 + 56 * (v / 100.0)) + 280
        self.setFixedSize(size_px, size_px); self.button.update()

    def show_dashboard(self):
        if not hasattr(self, 'dash_win') or not self.dash_win or not self.dash_win.isVisible():
            self.dash_win = DashboardWindow(self); self.dash_win.show()
        else: self.dash_win.raise_(); self.dash_win.activateWindow()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = CdulWidget()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
