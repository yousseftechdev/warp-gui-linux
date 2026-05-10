#!/usr/bin/env python3
"""
WARP Control GUI — single-page redesign
• No sidebar: everything lives on one scrollable main page
• Activity ticker showing what WARP is doing right now
• Desktop notifications on connect / connecting / disconnect
• System tray icon so you can hide the window and keep it running
"""

import sys
import subprocess
import re
import os
import socket
import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QScrollArea,
    QGraphicsDropShadowEffect, QSizePolicy, QTextEdit,
    QGridLayout, QLineEdit, QSystemTrayIcon, QMenu,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRectF, QPointF, pyqtProperty,
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QLinearGradient,
    QRadialGradient, QPen, QBrush, QIcon, QPalette, QPixmap,
    QAction,
)

# ─── Color Palette ────────────────────────────────────────────────────────────
BG_DEEP   = "#0a0c10"
BG_CARD   = "#0f1318"
BG_HOVER  = "#161b22"
BG_BORDER = "#1e2530"
ACCENT    = "#ffd166"
ACCENT2   = "#fbad41"
BLUE      = "#4d9fff"
GREEN     = "#3ada8e"
RED       = "#ff4d6a"
YELLOW    = "#f6821f"
TEXT_PRI  = "#e8edf2"
TEXT_SEC  = "#6b7685"
TEXT_DIM  = "#3a4252"


# ─── Warp CLI Backend ─────────────────────────────────────────────────────────
def run_cmd(args, timeout=8):
    try:
        r = subprocess.run(
            ["warp-cli"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "warp-cli not found", 1
    except subprocess.TimeoutExpired:
        return "", "timeout", 1


def get_warp_settings():
    try:
        result = subprocess.run(
            ["warp-cli", "settings"], capture_output=True, text=True, check=True,
        )
        settings = {}
        for line in result.stdout.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                key = re.sub(r'\([^)]*\)\t', '', key.strip())
                settings[key] = value.strip()
        return settings
    except subprocess.CalledProcessError:
        return {}


def get_status():
    out, err, code = run_cmd(["status"])
    settings = get_warp_settings()
    mode = settings.get("Mode", "Unknown")
    tunnel_type = settings.get("WARP tunnel protocol", "Unknown")
    data = {
        "raw": out,
        "connected": False,
        "connecting": False,
        "mode": mode,
        "tunnel_type": tunnel_type,
        "activity": "",
    }
    if not out:
        data["raw"] = err or "warp-cli not available"
        data["activity"] = err or "warp-cli not available"
        return data

    data["connected"] = "Connected" in out and "Disconnected" not in out
    data["connecting"] = "Connecting" in out

    # Pull the most descriptive activity line from the raw output
    activity_line = ""
    for line in out.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("Status update"):
            # Prefer lines that look like an action description
            if any(kw in stripped.lower() for kw in [
                "performing", "resolving", "establishing", "handshake",
                "authenticating", "fetching", "routing", "connected",
                "connecting", "disconnected", "registering", "probing",
                "checking", "waiting", "retrying", "failed", "success",
            ]):
                activity_line = stripped
                break
    if not activity_line:
        # Fall back to last non-empty line
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        activity_line = lines[-1] if lines else ""

    data["activity"] = activity_line

    if m := re.search(r"Mode: (.+)", out):
        data["mode"] = m.group(1).strip()
    if m := re.search(r"Tunnel Type: (.+)", out):
        data["tunnel_type"] = m.group(1).strip()

    return data


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
                capture_output=True, text=True, timeout=30,
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
        if self._glow_alpha > 0:
            g = QRadialGradient(
                float(r.center().x()), float(r.center().y()),
                max(r.width(), r.height()) * 0.7,
            )
            glow_c = QColor(self._color)
            glow_c.setAlpha(int(self._glow_alpha * 0.25))
            g.setColorAt(0, glow_c)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(r, g)
        path = QPainterPath()
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



class StatusOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 110)
        self._connected = False
        self._connecting = False
        self._pulse = 0.0
        self._t = 0.0
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def _tick(self):
        import math
        self._t += 0.1
        self._pulse = (math.sin(self._t) + 1) / 2
        self.update()

    def set_connected(self, v):
        self._connected = v
        self.update()

    def set_connecting(self, v):
        self._connecting = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        fcx, fcy = float(cx), float(cy)
        if self._connected:
            color = QColor(GREEN)
        elif self._connecting:
            color = QColor(YELLOW)
        else:
            color = QColor(TEXT_DIM)
        if self._connected or self._connecting:
            ring_alpha = int(self._pulse * 80)
            ring_r = float(42 + self._pulse * 8)
            ring_c = QColor(color)
            ring_c.setAlpha(ring_alpha)
            p.setPen(QPen(ring_c, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(fcx, fcy), ring_r, ring_r)
        glow_r = 35.0
        g = QRadialGradient(fcx, fcy, glow_r)
        inner = QColor(color)
        inner.setAlpha(60 if self._connected else 20)
        g.setColorAt(0, inner)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(fcx, fcy), glow_r, glow_r)
        core = QRadialGradient(fcx - 6, fcy - 6, 18.0)
        c1 = QColor(color).lighter(150 if self._connected else 100)
        c1.setAlpha(255)
        core.setColorAt(0, c1)
        core.setColorAt(1, color.darker(140))
        p.setBrush(core)
        p.setPen(QPen(color.lighter(120), 1.5))
        p.drawEllipse(QPointF(fcx, fcy), 20.0, 20.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(cx - 8, cy - 12, 9, 5)
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
        icon_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 15px;")
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {TEXT_SEC}; font-size: 10px; font-family: monospace; "
            f"letter-spacing: 1.5px; text-transform: uppercase;"
        )
        top.addWidget(icon_lbl)
        top.addWidget(lbl)
        top.addStretch()
        layout.addLayout(top)
        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(
            f"color: {TEXT_PRI}; font-size: 14px; font-weight: 600; font-family: monospace;"
        )
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
        self.append(
            f'<span style="color:{TEXT_SEC}">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


def _section_label(text):
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 10px; letter-spacing: 2.5px; "
        f"font-family: monospace; margin-top: 6px;"
    )
    return lbl


def _separator():
    sep = QFrame()
    sep.setFixedHeight(1)
    sep.setStyleSheet(f"background: {BG_BORDER}; margin: 4px 0;")
    return sep


# ─── Tray Icon Builder ────────────────────────────────────────────────────────
def _make_tray_icon(state: str) -> QIcon:
    """Draw a tiny coloured circle as the tray icon."""
    color_map = {"connected": GREEN, "connecting": YELLOW, "disconnected": RED}
    color = QColor(color_map.get(state, TEXT_DIM))
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 18, 18)
    p.end()
    return QIcon(px)


# ─── Main Window ──────────────────────────────────────────────────────────────
class WarpGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        # Tool windows are exempted from tiling in Hyprland and i3/sway.
        # We keep Qt.WindowType.Window so it still gets a taskbar entry on
        # desktop environments that care about that.
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.Tool)
        self.setWindowTitle("WARP Control")
        self.setMinimumSize(700, 600)
        self.resize(820, 860)
        self._workers: list[QThread] = []
        self._last_state: str = ""   # "connected" | "connecting" | "disconnected"

        self._setup_style()
        self._build_ui()
        self._setup_tray()
        self._setup_timer()
        self._refresh()

    # ── Style ─────────────────────────────────────────────────────────────────
    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BG_DEEP};
                color: {TEXT_PRI};
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QLabel {{ background: transparent; }}
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

    # ── System Tray ───────────────────────────────────────────────────────────
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon("disconnected"))
        self._tray.setToolTip("WARP Control")

        menu = QMenu()
        act_show = QAction("Show / Hide", self)
        act_show.triggered.connect(self._toggle_window)
        act_connect = QAction("Connect", self)
        act_connect.triggered.connect(lambda: self._cmd(["connect"], "Connect"))
        act_disconnect = QAction("Disconnect", self)
        act_disconnect.triggered.connect(lambda: self._cmd(["disconnect"], "Disconnect"))
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self._quit_app)

        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_connect)
        menu.addAction(act_disconnect)
        menu.addSeparator()
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit_app(self):
        if self._tray:
            self._tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        """Hide to tray instead of quitting if tray is available."""
        if self._tray and self._tray.isVisible():
            self.hide()
            e.ignore()
        else:
            for w in self._workers:
                w.quit()
            e.accept()

    # ── Desktop Notifications ─────────────────────────────────────────────────
    def _notify(self, title: str, msg: str, icon=QSystemTrayIcon.MessageIcon.Information):
        """Show a desktop notification via the tray balloon (if available),
        falling back to notify-send on Linux."""
        if self._tray and self._tray.isVisible():
            self._tray.showMessage(title, msg, icon, 4000)
        else:
            # Fallback: notify-send (Linux) – fire-and-forget
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "WARP Control", title, msg],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.setCentralWidget(scroll)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        scroll.setWidget(container)

        main = QVBoxLayout(container)
        main.setContentsMargins(28, 24, 28, 32)
        main.setSpacing(18)

        # ── Top bar ──────────────────────────────────────────────────────────
        topbar = QHBoxLayout()
        logo_icon = QLabel("◈")
        logo_icon.setStyleSheet(f"color: {ACCENT}; font-size: 22px;")
        logo_text = QLabel("WARP Control")
        logo_text.setStyleSheet(f"color: {TEXT_PRI}; font-size: 18px; font-weight: 700; letter-spacing: 2px;")
        self.last_update_lbl = QLabel("Last updated: —")
        self.last_update_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        topbar.addWidget(logo_icon)
        topbar.addWidget(logo_text)
        topbar.addStretch()
        topbar.addWidget(self.last_update_lbl)
        main.addLayout(topbar)

        # ── Hero status card ─────────────────────────────────────────────────
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
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(20)

        self.orb = StatusOrb()
        hero_layout.addWidget(self.orb)

        status_col = QVBoxLayout()
        status_col.setSpacing(6)
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet(
            f"color: {RED}; font-size: 24px; font-weight: 800; letter-spacing: 4px;"
        )
        self.tunnel_label = QLabel("Tunnel: —")
        self.tunnel_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; font-family: monospace;")
        self.mode_label = QLabel("Mode: —")
        self.mode_label.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; font-family: monospace;")
        status_col.addWidget(self.status_label)
        status_col.addWidget(self.tunnel_label)
        status_col.addWidget(self.mode_label)
        hero_layout.addLayout(status_col)
        hero_layout.addStretch()
        main.addWidget(hero)

        # ── Activity ticker ──────────────────────────────────────────────────
        activity_frame = QFrame()
        activity_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_CARD};
                border: 0px solid {BG_BORDER};
                border-radius: 10px;
            }}
        """)
        act_layout = QHBoxLayout(activity_frame)
        act_layout.setContentsMargins(16, 10, 16, 10)
        act_layout.setSpacing(10)
        act_icon = QLabel("⟳")
        act_icon.setStyleSheet(f"color: {ACCENT}; font-size: 14px;")
        act_title = QLabel("Activity:")
        act_title.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; font-family: monospace; letter-spacing: 1px;")
        self.activity_label = QLabel("Waiting for status…")
        self.activity_label.setStyleSheet(
            f"color: {TEXT_PRI}; font-size: 12px; font-family: 'JetBrains Mono', monospace;"
        )
        self.activity_label.setWordWrap(True)
        act_layout.addWidget(act_icon)
        act_layout.addWidget(act_title)
        act_layout.addWidget(self.activity_label, stretch=1)
        main.addWidget(activity_frame)

        # ── Quick actions ────────────────────────────────────────────────────
        main.addWidget(_section_label("Quick Actions"))
        actions = QHBoxLayout()
        actions.setSpacing(10)
        for txt, col, cb in [
            ("⟳  Connect",     GREEN,  lambda: self._cmd(["connect"], "Connect")),
            ("✕  Disconnect",  RED,    lambda: self._cmd(["disconnect"], "Disconnect")),
            ("↻  Restart svc", YELLOW, self._restart_service),
            ("⟲  Refresh",     BLUE,   self._refresh),
        ]:
            b = GlowButton(txt, col)
            b.setFixedHeight(40)
            b.setFont(QFont("monospace", 11))
            b.clicked.connect(cb)
            actions.addWidget(b)
        main.addLayout(actions)

        # ── Metrics grid ─────────────────────────────────────────────────────
        self.metric_tunnel = MetricCard("⟐", "TUNNEL TYPE")
        self.metric_mode   = MetricCard("◈", "WARP MODE")
        self.metric_status = MetricCard("◉", "STATUS")
        self.metric_time   = MetricCard("◷", "LOCAL TIME")
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self.metric_tunnel, 0, 0)
        grid.addWidget(self.metric_mode,   0, 1)
        grid.addWidget(self.metric_status, 1, 0)
        grid.addWidget(self.metric_time,   1, 1)
        main.addLayout(grid)

        main.addWidget(_separator())

        # ── Connection Modes ─────────────────────────────────────────────────
        main.addWidget(_section_label("Connection Modes"))
        modes_hint = QLabel("Switch between WARP modes — changes take effect immediately.")
        modes_hint.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
        main.addWidget(modes_hint)

        modes_data = [
            ("warp",        "◈ WARP",           GREEN,   "Full WARP tunnel — encrypts all traffic and routes through Cloudflare's network."),
            ("doh",         "◎ DNS over HTTPS",  BLUE,    "Only DNS queries go through Cloudflare. Good for ad/malware blocking without full VPN overhead."),
            ("warp+doh",    "⊞ WARP + DoH",      ACCENT,  "Full WARP tunnel combined with encrypted DNS. Maximum privacy. Recommended."),
            ("dot",         "◐ DNS over TLS",    ACCENT2, "Encrypts DNS via TLS. Similar privacy to DoH with a different protocol."),
            ("proxy",       "⊟ Proxy Mode",      YELLOW,  "Runs a local SOCKS5 proxy (127.0.0.1:40000). Route specific apps through WARP manually."),
            ("tunnel_only", "⊙ Tunnel Only",     TEXT_SEC,"Creates the WireGuard tunnel but doesn't override DNS. For advanced setups."),
        ]
        modes_grid = QGridLayout()
        modes_grid.setSpacing(10)
        for i, (mode_id, mode_name, color, mode_desc) in enumerate(modes_data):
            card = QFrame()
            card.setObjectName("modeCard")
            card.setStyleSheet(f"""
                #modeCard {{
                    background: {BG_CARD};
                    border: 1px solid {BG_BORDER};
                    border-radius: 12px;
                }}
                #modeCard:hover {{ border-color: {ACCENT}; }}
            """)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            left = QVBoxLayout()
            nm = QLabel(mode_name)
            nm.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600; font-family: monospace;")
            dsc = QLabel(mode_desc)
            dsc.setWordWrap(True)
            dsc.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px;")
            left.addWidget(nm)
            left.addWidget(dsc)
            cl.addLayout(left)
            btn = GlowButton(f"Set", color)
            btn.setFixedWidth(64)
            btn.setFixedHeight(32)
            btn.setFont(QFont("monospace", 11))
            btn.clicked.connect(lambda _, m=mode_id: self._set_mode(m))
            cl.addWidget(btn)
            modes_grid.addWidget(card, i // 2, i % 2)
        main.addLayout(modes_grid)

        main.addWidget(_separator())

        # ── Terminal ─────────────────────────────────────────────────────────
        main.addWidget(_section_label("Command Terminal"))
        term_hint = QLabel("Run warp-cli commands directly. Output is shown below.")
        term_hint.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px;")
        main.addWidget(term_hint)

        self.term_output = LogView()
        self.term_output.setMinimumHeight(200)
        self.term_output.setMaximumHeight(320)
        self.term_output.log("WARP Control Terminal ready. Enter a command below.", ACCENT)
        main.addWidget(self.term_output)

        input_row = QHBoxLayout()
        prompt = QLabel("warp-cli")
        prompt.setStyleSheet(f"color: {ACCENT}; font-family: monospace; font-size: 13px; font-weight: 700;")
        self.term_input = QLineEdit()
        self.term_input.setPlaceholderText("status / connect / disconnect / help …")
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
        main.addLayout(input_row)

        # Quick pills
        pills_label = QLabel("Quick commands:")
        pills_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        main.addWidget(pills_label)
        pills = QHBoxLayout()
        pills.setSpacing(8)
        for cmd in ["connect", "disconnect", "status", "account", "settings", "dns stats", "help"]:
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
        main.addLayout(pills)

        main.addWidget(_separator())

        # ── Footer ───────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        self.sb_status = QLabel("● Checking…")
        self.sb_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; font-family: monospace;")
        ver_lbl = QLabel("warp-gui v1.2")
        ver_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        footer.addWidget(self.sb_status)
        footer.addStretch()
        footer.addWidget(ver_lbl)
        main.addLayout(footer)

    # ── Timers ────────────────────────────────────────────────────────────────
    def _setup_timer(self):
        self.auto_timer = QTimer()
        self.auto_timer.timeout.connect(self._refresh)
        self.auto_timer.start(3000)

        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(
            lambda: self.metric_time.set_value(datetime.now().strftime("%H:%M:%S"))
        )
        self.clock_timer.start(1000)

    # ── Status logic ──────────────────────────────────────────────────────────
    def _refresh(self):
        w = StatusWorker()
        w.result.connect(self._apply_status)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _apply_status(self, data):
        connected  = data.get("connected", False)
        connecting = data.get("connecting", False)
        mode       = data.get("mode", "—")
        tunnel     = data.get("tunnel_type", "—")
        activity   = data.get("activity", "")

        self.orb.set_connected(connected)
        self.orb.set_connecting(connecting)

        new_state = "connected" if connected else ("connecting" if connecting else "disconnected")
        if new_state != self._last_state:
            self._fire_notification(new_state)
            self._last_state = new_state
            if self._tray:
                self._tray.setIcon(_make_tray_icon(new_state))
                self._tray.setToolTip(f"WARP — {new_state.capitalize()}")

        if connected:
            self.status_label.setText("CONNECTED")
            self.status_label.setStyleSheet(
                f"color: {GREEN}; font-size: 24px; font-weight: 800; letter-spacing: 4px;"
            )
            self.sb_status.setText(f"● Connected")
            self.sb_status.setStyleSheet(f"color: {GREEN}; font-size: 11px; font-family: monospace;")
            self.metric_status.set_value("Connected")
        elif connecting:
            self.status_label.setText("CONNECTING…")
            self.status_label.setStyleSheet(
                f"color: {YELLOW}; font-size: 24px; font-weight: 800; letter-spacing: 4px;"
            )
            self.sb_status.setText("○ Connecting")
            self.sb_status.setStyleSheet(f"color: {YELLOW}; font-size: 11px; font-family: monospace;")
            self.metric_status.set_value("Connecting")
        else:
            self.status_label.setText("DISCONNECTED")
            self.status_label.setStyleSheet(
                f"color: {RED}; font-size: 24px; font-weight: 800; letter-spacing: 4px;"
            )
            self.sb_status.setText("○ Disconnected")
            self.sb_status.setStyleSheet(f"color: {RED}; font-size: 11px; font-family: monospace;")
            self.metric_status.set_value("Disconnected")

        self.tunnel_label.setText(f"Tunnel: {tunnel}")
        self.mode_label.setText(f"Mode: {mode}")
        self.metric_tunnel.set_value(tunnel)
        self.metric_mode.set_value(mode)
        self.last_update_lbl.setText(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

        # Activity ticker
        if activity:
            self.activity_label.setText(activity)
        elif connected:
            self.activity_label.setText("Tunnel active — traffic is protected.")
        elif connecting:
            self.activity_label.setText("Establishing connection…")
        else:
            self.activity_label.setText("WARP is disconnected.")

    def _fire_notification(self, state: str):
        info  = QSystemTrayIcon.MessageIcon.Information
        warn  = QSystemTrayIcon.MessageIcon.Warning
        if state == "connected":
            self._notify("WARP Connected", "Your traffic is now protected by WARP.", info)
        elif state == "connecting":
            self._notify("WARP Connecting", "Establishing secure tunnel…", info)
        else:
            self._notify("WARP Disconnected", "The WARP tunnel has been closed.", warn)

    # ── Commands ──────────────────────────────────────────────────────────────
    def _cmd(self, args, label):
        w = CommandWorker(args, label)
        w.result.connect(lambda msg, ok: self._log_result(msg, ok))
        w.finished.connect(lambda: (
            self._refresh(),
            self._workers.remove(w) if w in self._workers else None,
        ))
        self._workers.append(w)
        w.start()

    def _log_result(self, msg, ok):
        color = GREEN if ok else RED
        self.term_output.log(msg, color)

    def _set_mode(self, mode):
        self.term_output.log(f"Setting mode → {mode}", ACCENT)
        self._cmd(["mode", mode], f"Set mode {mode}")

    def _restart_service(self):
        self.term_output.log("Requesting warp-svc restart (needs sudo)…", YELLOW)
        w = ServiceWorker()
        w.result.connect(lambda msg, ok: self.term_output.log(msg, GREEN if ok else RED))
        w.finished.connect(lambda: (
            self._refresh(),
            self._workers.remove(w) if w in self._workers else None,
        ))
        self._workers.append(w)
        w.start()

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


# ─── Single-Instance Guard ────────────────────────────────────────────────────
_LOCK_PORT = 49742

def _try_become_server():
    """
    Attempt to bind a local TCP socket on _LOCK_PORT.
    Returns the bound socket if we are the first instance, or None if another
    instance is already running (in which case we also poke it to raise itself).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", _LOCK_PORT))
        sock.listen(5)
        return sock
    except OSError:
        # Port already taken = another instance is running; wake it up
        try:
            ping = socket.create_connection(("127.0.0.1", _LOCK_PORT), timeout=1)
            ping.sendall(b"raise")
            ping.close()
        except OSError:
            pass
        sock.close()
        return None


def _start_listener(server_sock, window):
    """
    Background thread: accept connections from future instances and raise
    the window when they send the 'raise' message.
    """
    def _serve():
        while True:
            try:
                conn, _ = server_sock.accept()
                data = conn.recv(16)
                conn.close()
                if data == b"raise":
                    QTimer.singleShot(0, window._toggle_window)
            except OSError:
                break

    t = threading.Thread(target=_serve, daemon=True)
    t.start()


# ─── Entry Point ──────────────────────────────────────────────────────────────
def main():
    server_sock = _try_become_server()
    if server_sock is None:
        print("WARP Control is already running.")
        sys.exit(0)

    # Needed for tray + notifications on some desktop environments
    app = QApplication(sys.argv)
    app.setApplicationName("WARP Control")
    app.setOrganizationName("warp-gui")
    app.setQuitOnLastWindowClosed(False)

    window = WarpGUI()
    window.show()

    # Start listening for "raise" signals from future launch attempts
    _start_listener(server_sock, window)

    ret = app.exec()
    server_sock.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
