#!/usr/bin/env python3
"""
WARP Control — A modern GUI for Cloudflare WARP on Linux
Requires: PyQt6, warp-cli
Install: pip install PyQt6
"""

import sys
import subprocess
import json
import re
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QFrame, QScrollArea,
    QGraphicsDropShadowEffect, QSizePolicy, QStackedWidget,
    QGridLayout, QProgressBar, QTextEdit, QTabWidget, QSpacerItem
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRect, QSize, QPoint, pyqtProperty
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QLinearGradient,
    QRadialGradient, QPen, QBrush, QPixmap, QIcon, QFontDatabase,
    QPalette, QConicalGradient
)


# ─── Color Palette ────────────────────────────────────────────────────────────
BG_DEEP    = "#0a0c10"
BG_CARD    = "#0f1318"
BG_HOVER   = "#161b22"
BG_BORDER  = "#1e2530"
ACCENT     = "#f6821f"   # Cloudflare orange
ACCENT2    = "#fbad41"   # warm highlight
BLUE       = "#4d9fff"
GREEN      = "#3dfaae"
RED        = "#ff4d6a"
YELLOW     = "#ffd166"
TEXT_PRI   = "#e8edf2"
TEXT_SEC   = "#6b7685"
TEXT_DIM   = "#3a4252"
GLOW       = "rgba(246, 130, 31, 0.35)"


# ─── Warp CLI Backend ─────────────────────────────────────────────────────────
def run_cmd(args, timeout=8):
    try:
        r = subprocess.run(
            ["warp-cli"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "warp-cli not found", 1
    except subprocess.TimeoutExpired:
        return "", "timeout", 1

def get_warp_settings():
    try:
        result = subprocess.run(["warp-cli", "settings"], capture_output=True, text=True, check=True)
        settings = {}
        for line in result.stdout.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                key = re.sub(r'\([^)]*\)\t', '', key.strip())
                settings[key] = value.strip()
                
        return settings
    except subprocess.CalledProcessError as e:
        print(f"Error getting Warp settings: {e}")
        return {}

def get_status():
    out, err, code = run_cmd(["status"])
    mode = get_warp_settings().get("Mode", "Unknown")
    tunnel_type = get_warp_settings().get("WARP tunnel protocol", "Unknown")
    data = {
        "raw": out,
        "connected": False,
        "mode": mode,
        "tunnel_type": tunnel_type,
    }
    if not out:
        data["raw"] = err or "warp-cli not available"
        return data

    data["connected"] = "Connected" in out and "Disconnected" not in out

    if m := re.search(r"Status update: (.+)", out):
        data["status_label"] = m.group(1).strip()

    if m := re.search(r"Mode: (.+)", out):
        data["mode"] = m.group(1).strip()

    if m := re.search(r"Tunnel Type: (.+)", out):
        data["tunnel_type"] = m.group(1).strip()

    return data


def get_account():
    out, _, _ = run_cmd(["account"])
    return out if out else "Not registered"


def get_settings():
    out, _, _ = run_cmd(["settings"])
    return out if out else ""


def get_dns_stats():
    out, _, _ = run_cmd(["dns", "stats"], timeout=5)
    return out if out else ""


# ─── Worker Threads ───────────────────────────────────────────────────────────
class StatusWorker(QThread):
    result = pyqtSignal(dict)

    def run(self):
        self.result.emit(get_status())


class CommandWorker(QThread):
    result = pyqtSignal(str, bool)

    def __init__(self, args, label=""):
        super().__init__()
        self.args = args
        self.label = label

    def run(self):
        out, err, code = run_cmd(self.args)
        success = code == 0
        msg = out if out else err
        self.result.emit(f"[{self.label}] {msg}" if self.label else msg, success)


class ServiceWorker(QThread):
    result = pyqtSignal(str, bool)

    def run(self):
        try:
            r = subprocess.run(
                ["sudo", "systemctl", "restart", "warp-svc"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                self.result.emit("warp-svc restarted successfully", True)
            else:
                self.result.emit(r.stderr.strip() or "Failed to restart", False)
        except Exception as e:
            self.result.emit(str(e), False)


# ─── Custom Widgets ───────────────────────────────────────────────────────────
class GlowButton(QPushButton):
    def __init__(self, text, color=ACCENT, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._glow_alpha = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"glow_alpha")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_glow_alpha(self): return self._glow_alpha
    def set_glow_alpha(self, v):
        self._glow_alpha = v
        self.update()
    glow_alpha = pyqtProperty(int, get_glow_alpha, set_glow_alpha)

    def enterEvent(self, e):
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(255)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(0)
        self._anim.start()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        # Glow backdrop
        if self._glow_alpha > 0:
            g = QRadialGradient(float(r.center().x()), float(r.center().y()), max(r.width(), r.height()) * 0.7)
            glow_c = QColor(self._color)
            glow_c.setAlpha(int(self._glow_alpha * 0.25))
            g.setColorAt(0, glow_c)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(r, g)

        # Border + fill
        path = QPainterPath()
        from PyQt6.QtCore import QRectF
        path.addRoundedRect(QRectF(r.adjusted(1, 1, -1, -1)), 8, 8)
        if self.isDown():
            p.fillPath(path, QBrush(self._color.darker(130)))
        elif self._glow_alpha > 0:
            lighter = QColor(self._color)
            lighter.setAlpha(220 + int(self._glow_alpha * 0.14))
            p.fillPath(path, QBrush(lighter))
        else:
            p.fillPath(path, QBrush(self._color.darker(115)))

        pen = QPen(self._color.lighter(130))
        pen.setWidth(1)
        p.strokePath(path, pen)

        p.setPen(QColor(TEXT_PRI))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self._pos = 4.0
        self.setFixedSize(56, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"pos_x")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)

    def get_pos_x(self): return self._pos
    def set_pos_x(self, v):
        self._pos = v
        self.update()
    pos_x = pyqtProperty(float, get_pos_x, set_pos_x)

    def set_on(self, on):
        self._on = on
        self._pos = 32.0 if on else 4.0
        self.update()

    def mousePressEvent(self, e):
        self._on = not self._on
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(32.0 if self._on else 4.0)
        self._anim.start()
        self.toggled.emit(self._on)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(0, 4, 0, -4)
        track_color = QColor(ACCENT) if self._on else QColor(BG_BORDER)
        p.setBrush(track_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(track, 10, 10)
        p.setBrush(QColor(TEXT_PRI))
        p.drawEllipse(int(self._pos), 4, 20, 20)
        p.end()


class StatusOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._connected = False
        self._pulse = 0.0
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)
        self._t = 0.0

    def _tick(self):
        import math
        self._t += 0.05
        self._pulse = (math.sin(self._t) + 1) / 2
        self.update()

    def set_connected(self, v):
        self._connected = v
        self.update()

    def paintEvent(self, e):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2

        color = QColor(GREEN) if self._connected else QColor(TEXT_DIM)

        from PyQt6.QtCore import QPointF
        fcx, fcy = float(cx), float(cy)

        # Outer pulse ring
        if self._connected:
            ring_alpha = int(self._pulse * 80)
            ring_r = float(45 + self._pulse * 8)
            ring_c = QColor(GREEN)
            ring_c.setAlpha(ring_alpha)
            p.setPen(QPen(ring_c, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(fcx, fcy), ring_r, ring_r)

        # Mid glow
        glow_r = 38.0
        g = QRadialGradient(fcx, fcy, glow_r)
        inner = QColor(color)
        inner.setAlpha(60 if self._connected else 20)
        g.setColorAt(0, inner)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(fcx, fcy), glow_r, glow_r)

        # Core orb
        core = QRadialGradient(fcx - 6, fcy - 6, 20.0)
        c1 = QColor(color).lighter(150 if self._connected else 100)
        c1.setAlpha(255)
        core.setColorAt(0, c1)
        core.setColorAt(1, color.darker(140))
        p.setBrush(core)
        pen = QPen(color.lighter(120), 1.5)
        p.setPen(pen)
        p.drawEllipse(QPointF(fcx, fcy), 22.0, 22.0)

        # Specular highlight
        p.setPen(Qt.PenStyle.NoPen)
        hi = QColor(255, 255, 255, 60)
        p.setBrush(hi)
        p.drawEllipse(cx - 9, cy - 13, 10, 6)
        p.end()


class MetricCard(QFrame):
    def __init__(self, icon, label, value="—", parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setStyleSheet(f"""
            #metricCard {{
                background: {BG_CARD};
                border: 1px solid {BG_BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 16px;")
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; font-family: 'JetBrains Mono', monospace; letter-spacing: 1.5px; text-transform: uppercase;")
        top.addWidget(icon_lbl)
        top.addWidget(lbl)
        top.addStretch()
        layout.addLayout(top)

        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(f"color: {TEXT_PRI}; font-size: 15px; font-weight: 600; font-family: 'JetBrains Mono', monospace;")
        layout.addWidget(self.value_lbl)

    def set_value(self, v):
        self.value_lbl.setText(v)


class LogView(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setObjectName("logView")
        self.setStyleSheet(f"""
            QTextEdit#logView {{
                background: {BG_DEEP};
                color: {GREEN};
                font-family: 'JetBrains Mono', 'Fira Code', monospace;
                font-size: 12px;
                border: 1px solid {BG_BORDER};
                border-radius: 8px;
                padding: 10px;
            }}
        """)

    def log(self, msg, color=None):
        ts = datetime.now().strftime("%H:%M:%S")
        color = color or GREEN
        self.append(f'<span style="color:{TEXT_SEC}">[{ts}]</span> <span style="color:{color}">{msg}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ─── Main Window ──────────────────────────────────────────────────────────────
class WarpGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WARP Control")
        self.setMinimumSize(820, 680)
        self.resize(900, 720)
        self._workers = []  # keep refs alive

        self._setup_fonts()
        self._setup_style()
        self._build_ui()
        self._setup_timer()
        self._refresh()

    def _setup_fonts(self):
        # Try to load a mono font; fall back gracefully
        pass

    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BG_DEEP};
                color: {TEXT_PRI};
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QLabel {{ background: transparent; }}
            QComboBox {{
                background: {BG_CARD};
                color: {TEXT_PRI};
                border: 1px solid {BG_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QComboBox::drop-down {{ border: none; padding-right: 8px; }}
            QComboBox QAbstractItemView {{
                background: {BG_HOVER};
                color: {TEXT_PRI};
                border: 1px solid {BG_BORDER};
                selection-background-color: {ACCENT};
                selection-color: #000;
            }}
            QScrollBar:vertical {{
                background: {BG_CARD};
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {BG_BORDER};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QTabWidget::pane {{ border: 1px solid {BG_BORDER}; border-radius: 10px; background: {BG_CARD}; }}
            QTabBar::tab {{
                background: {BG_DEEP};
                color: {TEXT_SEC};
                padding: 8px 20px;
                border: 1px solid transparent;
                border-bottom: none;
                margin-right: 2px;
                border-radius: 8px 8px 0 0;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background: {BG_CARD};
                color: {TEXT_PRI};
                border-color: {BG_BORDER};
            }}
            QTabBar::tab:hover:!selected {{ color: {TEXT_PRI}; }}
            QPushButton {{
                background: {BG_CARD};
                color: {TEXT_PRI};
                border: 1px solid {BG_BORDER};
                border-radius: 8px;
                padding: 7px 18px;
            }}
            QPushButton:hover {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
            QPushButton:pressed {{ background: {BG_DEEP}; }}
        """)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background: {BG_CARD};
                border-right: 1px solid {BG_BORDER};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(16, 20, 16, 20)
        sb_layout.setSpacing(4)

        # Logo
        logo_row = QHBoxLayout()
        logo_icon = QLabel("◈")
        logo_icon.setStyleSheet(f"color: {ACCENT}; font-size: 24px;")
        logo_text = QLabel("WARP")
        logo_text.setStyleSheet(f"color: {TEXT_PRI}; font-size: 18px; font-weight: 700; letter-spacing: 3px;")
        logo_row.addWidget(logo_icon)
        logo_row.addWidget(logo_text)
        logo_row.addStretch()
        sb_layout.addLayout(logo_row)

        sub_logo = QLabel("Cloudflare Control Panel")
        sub_logo.setStyleSheet(f"color: {TEXT_SEC}; font-size: 10px; letter-spacing: 1px; margin-bottom: 16px;")
        sb_layout.addWidget(sub_logo)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {BG_BORDER};")
        sb_layout.addWidget(sep)
        sb_layout.addSpacing(12)

        # Nav
        self._nav_btns = []
        nav_items = [
            ("▣", "Dashboard", 0),
            ("◎", "Modes", 1),
            ("⊞", "DNS & Stats", 2),
            ("⊟", "Account", 3),
            ("⌘", "Terminal", 4),
        ]
        self.stack = QStackedWidget()
        for icon, label, idx in nav_items:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_SEC};
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 9px 12px;
                    font-size: 13px;
                }}
                QPushButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRI}; }}
                QPushButton:checked {{ background: {BG_HOVER}; color: {ACCENT}; border-left: 2px solid {ACCENT}; }}
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=idx: self._nav(i))
            sb_layout.addWidget(btn)
            self._nav_btns.append(btn)

        sb_layout.addStretch()

        # Status indicator in sidebar
        self.sb_status = QLabel("● Checking...")
        self.sb_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; font-family: monospace;")
        sb_layout.addWidget(self.sb_status)

        ver_lbl = QLabel("warp-gui v1.0")
        ver_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 141px;")
        sb_layout.addWidget(ver_lbl)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack)

        # ── Pages ─────────────────────────────────────────────────────────────
        self.stack.addWidget(self._build_dashboard())
        self.stack.addWidget(self._build_modes())
        self.stack.addWidget(self._build_dns())
        self.stack.addWidget(self._build_account())
        self.stack.addWidget(self._build_terminal())

        self._nav(0)

    def _nav(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)

    # ── Dashboard ──────────────────────────────────────────────────────────────
    def _build_dashboard(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setStyleSheet(f"color: {TEXT_PRI}; font-size: 22px; font-weight: 700;")
        self.last_update_lbl = QLabel("Last updated: —")
        self.last_update_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.last_update_lbl)
        layout.addLayout(header)

        # Hero status card
        hero = QFrame()
        hero.setObjectName("hero")
        hero.setStyleSheet(f"""
            #hero {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {BG_CARD}, stop:1 #111820);
                border: 1px solid {BG_BORDER};
                border-radius: 16px;
            }}
        """)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(28, 24, 28, 24)
        hero_layout.setSpacing(24)

        # Orb
        self.orb = StatusOrb()
        hero_layout.addWidget(self.orb)

        # Status text
        status_col = QVBoxLayout()
        status_col.setSpacing(8)
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 26px; font-weight: 800; letter-spacing: 4px;")
        self.tunnel_label = QLabel("Tunnel: —")
        self.tunnel_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; font-family: monospace;")
        self.mode_label = QLabel("Mode: —")
        self.mode_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; font-family: monospace;")
        status_col.addWidget(self.status_label)
        status_col.addWidget(self.tunnel_label)
        status_col.addWidget(self.mode_label)
        hero_layout.addLayout(status_col)
        hero_layout.addStretch()

        # Big toggle
        toggle_col = QVBoxLayout()
        toggle_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_toggle = ToggleSwitch()
        self.big_toggle.toggled.connect(self._on_big_toggle)
        toggle_col.addWidget(QLabel("Power"))
        toggle_col.itemAt(0).widget().setStyleSheet(f"color:{TEXT_SEC}; font-size:11px; text-align:center;")
        toggle_col.addWidget(self.big_toggle, alignment=Qt.AlignmentFlag.AlignCenter)
        hero_layout.addLayout(toggle_col)
        layout.addWidget(hero)

        # Quick Actions
        qa_label = QLabel("Quick Actions")
        qa_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; letter-spacing: 2px; text-transform: uppercase;")
        layout.addWidget(qa_label)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        btns = [
            ("⟳  Connect",     GREEN,  lambda: self._cmd(["connect"], "Connect")),
            ("✕  Disconnect",  RED,    lambda: self._cmd(["disconnect"], "Disconnect")),
            ("↻  Restart svc", YELLOW, self._restart_service),
            ("⟲  Refresh",     BLUE,   self._refresh),
        ]
        for txt, col, cb in btns:
            b = GlowButton(txt, col)
            b.setFixedHeight(40)
            b.setFont(QFont("monospace", 11))
            b.clicked.connect(cb)
            actions.addWidget(b)
        layout.addLayout(actions)

        # Metrics grid
        self.metric_tunnel  = MetricCard("⟐", "TUNNEL TYPE")
        self.metric_mode    = MetricCard("◈", "WARP MODE")
        self.metric_status  = MetricCard("◉", "STATUS")
        self.metric_time    = MetricCard("◷", "LOCAL TIME")

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self.metric_tunnel, 0, 0)
        grid.addWidget(self.metric_mode, 0, 1)
        grid.addWidget(self.metric_status, 1, 0)
        grid.addWidget(self.metric_time, 1, 1)
        layout.addLayout(grid)

        layout.addStretch()
        return w

    # ── Modes ──────────────────────────────────────────────────────────────────
    def _build_modes(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        title = QLabel("Connection Modes")
        title.setStyleSheet(f"color: {TEXT_PRI}; font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        desc = QLabel("Switch between WARP modes. Changes take effect immediately.")
        desc.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
        layout.addWidget(desc)

        modes_data = [
            ("warp",           "◈ WARP",            GREEN,  "Full WARP tunnel — encrypts all traffic and routes through Cloudflare's network for privacy and performance."),
            ("doh",            "◎ DNS over HTTPS",  BLUE,   "Only DNS queries go through Cloudflare. Good for ad/malware blocking without full VPN overhead."),
            ("warp+doh",       "⊞ WARP + DoH",      ACCENT, "Full WARP tunnel combined with encrypted DNS. Maximum privacy. Recommended for most users."),
            ("dot",            "◐ DNS over TLS",    ACCENT2,"Encrypts DNS via TLS rather than HTTPS. Similar privacy to DoH with different protocol mechanics."),
            ("proxy",          "⊟ Proxy Mode",      YELLOW, "Runs a local SOCKS5 proxy (127.0.0.1:40000). Route specific apps through WARP manually."),
            ("tunnel_only",    "⊙ Tunnel Only",     TEXT_SEC,"Creates the WireGuard tunnel but doesn't override DNS. For advanced routing setups."),
        ]

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(10)

        for mode_id, mode_name, color, mode_desc in modes_data:
            card = QFrame()
            card.setObjectName("modeCard")
            card.setStyleSheet(f"""
                #modeCard {{
                    background: {BG_CARD};
                    border: 1px solid {BG_BORDER};
                    border-radius: 12px;
                }}
                #modeCard:hover {{
                    border-color: {ACCENT};
                }}
            """)
            c_layout = QHBoxLayout(card)
            c_layout.setContentsMargins(20, 16, 20, 16)

            left = QVBoxLayout()
            nm = QLabel(mode_name)
            nm.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 600; font-family: monospace;")
            dsc = QLabel(mode_desc)
            dsc.setWordWrap(True)
            dsc.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
            left.addWidget(nm)
            left.addWidget(dsc)
            c_layout.addLayout(left)

            btn = GlowButton(f"Set {mode_id}", color)
            btn.setFixedWidth(120)
            btn.setFixedHeight(36)
            btn.setFont(QFont("monospace", 11))
            btn.clicked.connect(lambda _, m=mode_id: self._set_mode(m))
            c_layout.addWidget(btn)
            inner_layout.addWidget(card)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        return w

    # ── DNS & Stats ────────────────────────────────────────────────────────────
    def _build_dns(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("DNS & Statistics")
        title.setStyleSheet(f"color: {TEXT_PRI}; font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        refresh_btn = GlowButton("⟲  Refresh Stats", BLUE)
        refresh_btn.setFixedWidth(160)
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(self._refresh_dns)
        layout.addWidget(refresh_btn)

        self.dns_output = LogView()
        self.dns_output.setMinimumHeight(200)
        layout.addWidget(self.dns_output)

        # Settings section
        settings_label = QLabel("Current Settings")
        settings_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; letter-spacing: 2px;")
        layout.addWidget(settings_label)

        self.settings_output = LogView()
        self.settings_output.setMinimumHeight(180)
        layout.addWidget(self.settings_output)

        # Disconnect on network change toggle
        pref_row = QHBoxLayout()
        pref_lbl = QLabel("Extra options")
        pref_lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")

        btn_rotation = GlowButton("⟳ Rotate Keys", ACCENT2)
        btn_rotation.setFixedHeight(36)
        btn_rotation.clicked.connect(lambda: self._cmd(["rotate-keys"], "Rotate Keys"))

        btn_reset_settings = GlowButton("↺ Reset Settings", RED)
        btn_reset_settings.setFixedHeight(36)
        btn_reset_settings.clicked.connect(lambda: self._cmd(["settings", "reset"], "Reset Settings"))

        pref_row.addWidget(pref_lbl)
        pref_row.addStretch()
        pref_row.addWidget(btn_rotation)
        pref_row.addWidget(btn_reset_settings)
        layout.addLayout(pref_row)
        return w

    # ── Account ───────────────────────────────────────────────────────────────
    def _build_account(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Account")
        title.setStyleSheet(f"color: {TEXT_PRI}; font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        self.account_output = LogView()
        layout.addWidget(self.account_output)

        btn_row = QHBoxLayout()
        for label, args, color in [
            ("⟲  Refresh",     ["account"],                 BLUE),
            ("⊞  Register",    ["registration", "new"],     GREEN),
            ("✕  Delete Reg.", ["registration", "delete"],  RED),
        ]:
            b = GlowButton(label, color)
            b.setFixedHeight(38)
            b.clicked.connect(lambda _, a=args, l=label: self._cmd_account(a, l))
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {BG_BORDER};")
        layout.addWidget(sep)

        # License key input
        lic_label = QLabel("WARP+ License Key")
        lic_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; letter-spacing: 1px;")
        layout.addWidget(lic_label)

        lic_row = QHBoxLayout()
        from PyQt6.QtWidgets import QLineEdit
        self.lic_input = QLineEdit()
        self.lic_input.setPlaceholderText("xxxxxxxx-xxxxxxxx-xxxxxxxx")
        self.lic_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_CARD};
                color: {TEXT_PRI};
                border: 1px solid {BG_BORDER};
                border-radius: 8px;
                padding: 8px 14px;
                font-family: monospace;
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; }}
        """)
        lic_btn = GlowButton("Apply Key", ACCENT)
        lic_btn.setFixedWidth(110)
        lic_btn.setFixedHeight(38)
        lic_btn.clicked.connect(self._apply_license)
        lic_row.addWidget(self.lic_input)
        lic_row.addWidget(lic_btn)
        layout.addLayout(lic_row)
        layout.addStretch()
        return w

    # ── Terminal ──────────────────────────────────────────────────────────────
    def _build_terminal(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("Command Terminal")
        title.setStyleSheet(f"color: {TEXT_PRI}; font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        desc = QLabel("Run warp-cli commands directly. Output is shown below.")
        desc.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
        layout.addWidget(desc)

        self.term_output = LogView()
        self.term_output.setMinimumHeight(340)
        self.term_output.log("WARP Control Terminal ready. Enter a command below.", ACCENT)
        layout.addWidget(self.term_output)

        from PyQt6.QtWidgets import QLineEdit
        input_row = QHBoxLayout()
        prompt = QLabel("warp-cli")
        prompt.setStyleSheet(f"color: {ACCENT}; font-family: monospace; font-size: 13px; font-weight: 700;")
        self.term_input = QLineEdit()
        self.term_input.setPlaceholderText("status / connect / disconnect / help ...")
        self.term_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_CARD};
                color: {GREEN};
                border: 1px solid {BG_BORDER};
                border-radius: 8px;
                padding: 8px 14px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; }}
        """)
        self.term_input.returnPressed.connect(self._run_terminal)
        run_btn = GlowButton("Run ↵", ACCENT)
        run_btn.setFixedWidth(80)
        run_btn.setFixedHeight(38)
        run_btn.clicked.connect(self._run_terminal)
        input_row.addWidget(prompt)
        input_row.addWidget(self.term_input)
        input_row.addWidget(run_btn)
        layout.addLayout(input_row)

        # Quick cmd pills
        pills_label = QLabel("Quick commands:")
        pills_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(pills_label)

        pills = QHBoxLayout()
        pills.setSpacing(8)
        for cmd in ["status", "account", "settings", "dns stats", "help"]:
            b = QPushButton(cmd)
            b.setFixedHeight(28)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {BG_CARD};
                    color: {TEXT_SEC};
                    border: 1px solid {BG_BORDER};
                    border-radius: 6px;
                    padding: 0 12px;
                    font-family: monospace;
                    font-size: 11px;
                }}
                QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
            """)
            b.clicked.connect(lambda _, c=cmd: self._quick_cmd(c))
            pills.addWidget(b)
        pills.addStretch()
        layout.addLayout(pills)
        return w

    # ── Logic ─────────────────────────────────────────────────────────────────
    def _setup_timer(self):
        self.auto_timer = QTimer()
        self.auto_timer.timeout.connect(self._refresh)
        self.auto_timer.start(100)

        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

    def _update_clock(self):
        self.metric_time.set_value(datetime.now().strftime("%H:%M:%S"))

    def _refresh(self):
        w = StatusWorker()
        w.result.connect(self._apply_status)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _apply_status(self, data):
        connected = data.get("connected", False)
        mode = data.get("mode", "—")
        tunnel = data.get("tunnel_type", "—")
        raw = data.get("raw", "")

        self.orb.set_connected(connected)
        self.big_toggle.set_on(connected)

        if connected:
            self.status_label.setText("CONNECTED")
            self.status_label.setStyleSheet(f"color: {GREEN}; font-size: 26px; font-weight: 800; letter-spacing: 4px;")
            self.sb_status.setText(f"● Connected")
            self.sb_status.setStyleSheet(f"color: {GREEN}; font-size: 11px; font-family: monospace;")
        else:
            self.status_label.setText("DISCONNECTED")
            self.status_label.setStyleSheet(f"color: {RED}; font-size: 26px; font-weight: 800; letter-spacing: 4px;")
            self.sb_status.setText("○ Disconnected")
            self.sb_status.setStyleSheet(f"color: {RED}; font-size: 11px; font-family: monospace;")

        self.tunnel_label.setText(f"Tunnel: {tunnel}")
        self.mode_label.setText(f"Mode: {mode}")

        self.metric_tunnel.set_value(tunnel)
        self.metric_mode.set_value(mode)
        self.metric_status.set_value("Connected" if connected else "Disconnected")

        self.last_update_lbl.setText(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

    def _cmd(self, args, label):
        w = CommandWorker(args, label)
        w.result.connect(lambda msg, ok: self._log_result(msg, ok))
        w.finished.connect(lambda: (
            self._refresh(),
            self._workers.remove(w) if w in self._workers else None
        ))
        self._workers.append(w)
        w.start()

    def _cmd_account(self, args, label):
        w = CommandWorker(args, label)
        w.result.connect(lambda msg, ok: (
            self.account_output.log(msg, GREEN if ok else RED)
        ))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()
        # Also refresh account view
        self._refresh_account()

    def _log_result(self, msg, ok):
        color = GREEN if ok else RED
        # Log to terminal if it exists
        if hasattr(self, 'term_output'):
            self.term_output.log(msg, color)

    def _on_big_toggle(self, on):
        if on:
            self._cmd(["connect"], "Connect")
        else:
            self._cmd(["disconnect"], "Disconnect")

    def _set_mode(self, mode):
        self._cmd(["mode", mode], f"Set mode {mode}")
        if hasattr(self, 'term_output'):
            self.term_output.log(f"Setting mode → {mode}", ACCENT)

    def _restart_service(self):
        if hasattr(self, 'term_output'):
            self.term_output.log("Requesting warp-svc restart (needs sudo)...", YELLOW)
        w = ServiceWorker()
        w.result.connect(lambda msg, ok: (
            self.term_output.log(msg, GREEN if ok else RED) if hasattr(self, 'term_output') else None
        ))
        w.finished.connect(lambda: (
            self._refresh(),
            self._workers.remove(w) if w in self._workers else None
        ))
        self._workers.append(w)
        w.start()

    def _refresh_dns(self):
        self.dns_output.log("Fetching DNS stats...", ACCENT)
        w = CommandWorker(["dns", "stats"], "DNS Stats")
        w.result.connect(lambda msg, ok: self.dns_output.log(msg, GREEN if ok else RED))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

        ws = CommandWorker(["settings"], "Settings")
        ws.result.connect(lambda msg, ok: self.settings_output.log(msg, TEXT_PRI if ok else RED))
        ws.finished.connect(lambda: self._workers.remove(ws) if ws in self._workers else None)
        self._workers.append(ws)
        ws.start()

    def _refresh_account(self):
        w = CommandWorker(["account"], "Account")
        w.result.connect(lambda msg, ok: self.account_output.log(msg, TEXT_PRI if ok else RED))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _apply_license(self):
        key = self.lic_input.text().strip()
        if not key:
            return
        self._cmd(["registration", "license", key], "Apply License")
        self.lic_input.clear()

    def _run_terminal(self):
        text = self.term_input.text().strip()
        if not text:
            return
        self.term_output.log(f"$ warp-cli {text}", ACCENT2)
        args = text.split()
        w = CommandWorker(args)
        w.result.connect(lambda msg, ok: self.term_output.log(msg, GREEN if ok else RED))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()
        self.term_input.clear()

    def _quick_cmd(self, cmd):
        self.term_input.setText(cmd)
        self._run_terminal()

    def closeEvent(self, e):
        for w in self._workers:
            w.quit()
        e.accept()


# ─── Entry Point ──────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WARP Control")
    app.setOrganizationName("warp-gui")

    # Try to set a nice app icon using text
    window = WarpGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
