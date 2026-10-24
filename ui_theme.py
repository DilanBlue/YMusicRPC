"""UI Theme tokens, typography, SVG icon renderer, and styles for YMusic Discord RPC."""

import glob
import os
import sys
from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

try:
    from PyQt6.QtSvg import QSvgRenderer
    HAS_QT_SVG = True
except ImportError:
    HAS_QT_SVG = False

# ---------------------------------------------------------
# Color Tokens
# ---------------------------------------------------------
BG = "#0c0b10"
SURFACE = "#15141b"
SURFACE2 = "#1c1b24"
LINE = "rgba(255, 255, 255, 0.07)"
LINE_SOLID = "#22202c"
TEXT = "#f4f2f7"
MUTED = "#a29fae"
DIM = "#6f6c7a"
ACCENT = "#ffd21f"
ACCENT_INK = "#1a1500"
OK = "#3ddc97"
WARN = "#f5b73d"
ERR = "#ff6b6b"
DISCORD = "#5865F2"

# ---------------------------------------------------------
# Path resolution
# ---------------------------------------------------------
def resource_path(relative_path: str) -> str:
    """Resolve path for development or PyInstaller bundle."""
    base_dir = getattr(sys, "_MEIPASS", None)
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, relative_path))


# ---------------------------------------------------------
# Fonts & Typography
# ---------------------------------------------------------
UI_FONT_FAMILY = "Segoe UI"
MONO_FONT_FAMILY = "Cascadia Mono"
_FONTS_INITIALIZED = False


def init_fonts():
    """Register custom fonts into QFontDatabase with fallback check."""
    global UI_FONT_FAMILY, MONO_FONT_FAMILY, _FONTS_INITIALIZED
    if _FONTS_INITIALIZED:
        return
    _FONTS_INITIALIZED = True

    fonts_pattern = resource_path("assets/fonts/*.ttf")
    loaded_families = set()
    for fpath in glob.glob(fonts_pattern):
        fid = QFontDatabase.addApplicationFont(fpath)
        if fid != -1:
            for fam in QFontDatabase.applicationFontFamilies(fid):
                loaded_families.add(fam)

    if any("Onest" in f for f in loaded_families):
        UI_FONT_FAMILY = "Onest"
    else:
        UI_FONT_FAMILY = "Segoe UI"

    if any("JetBrains Mono" in f for f in loaded_families):
        MONO_FONT_FAMILY = "JetBrains Mono"
    else:
        MONO_FONT_FAMILY = "Cascadia Mono"


def font_ui(size: float = 13, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(UI_FONT_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def font_mono(size: float = 12.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(MONO_FONT_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


# ---------------------------------------------------------
# SVG Icon Rendering & Caching
# ---------------------------------------------------------
_SVG_CACHE: dict[tuple, QPixmap] = {}


def svg_pixmap(name: str, size: int = 24, color: str | None = None, dpr: float = 1.0) -> QPixmap:
    """Render an SVG icon with crisp HiDPI scaling and optional color override."""
    if not name.endswith(".svg"):
        name = f"{name}.svg"

    cache_key = (name, size, color, round(dpr, 2))
    if cache_key in _SVG_CACHE:
        return _SVG_CACHE[cache_key]

    fpath = resource_path(os.path.join("assets", "icons", name))
    if not os.path.exists(fpath):
        # Graceful empty pixmap
        pix = QPixmap(int(size * dpr), int(size * dpr))
        pix.fill(Qt.GlobalColor.transparent)
        pix.setDevicePixelRatio(dpr)
        return pix

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            svg_data = f.read()
    except Exception:
        svg_data = ""

    if color and svg_data:
        svg_data = svg_data.replace("currentColor", color)

    scaled_px = max(1, int(round(size * dpr)))
    pix = QPixmap(scaled_px, scaled_px)
    pix.fill(Qt.GlobalColor.transparent)

    if HAS_QT_SVG and svg_data:
        try:
            renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
            if renderer.isValid():
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                renderer.render(painter, QRectF(0, 0, scaled_px, scaled_px))
                painter.end()
        except Exception:
            pass
    else:
        # Simple geometric fallback
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color or TEXT), 2))
        painter.drawRect(2, 2, scaled_px - 4, scaled_px - 4)
        painter.end()

    pix.setDevicePixelRatio(dpr)
    _SVG_CACHE[cache_key] = pix
    return pix


def svg_icon(name: str, size: int = 24, color: str | None = None) -> QIcon:
    """Convenience helper to get a QIcon from svg_pixmap."""
    return QIcon(svg_pixmap(name, size, color))


# ---------------------------------------------------------
# Application Stylesheet (QSS)
# ---------------------------------------------------------
def get_app_qss() -> str:
    return f"""
        QMainWindow, QWidget#CentralWidget {{
            background-color: {BG};
            color: {TEXT};
            font-family: '{UI_FONT_FAMILY}', -apple-system, sans-serif;
        }}
        QFrame {{
            border: none;
            background-color: transparent;
        }}
        QLabel {{
            border: none;
            background-color: transparent;
            color: {TEXT};
        }}
        
        /* Base Card Styling */
        QFrame#CardTrack, QFrame#CardControls, QFrame#CardIP, QFrame#CardLog {{
            background-color: {SURFACE};
            border: 1px solid {LINE};
            border-radius: 14px;
        }}

        /* Buttons */
        QPushButton {{
            font-family: '{UI_FONT_FAMILY}';
            border-radius: 10px;
            padding: 8px 14px;
            font-size: 13px;
            font-weight: 500;
            outline: none;
        }}
        QPushButton:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        QCheckBox {{
            outline: none;
        }}
        QCheckBox:focus {{
            outline: none;
        }}
        
        QPushButton.primary-btn {{
            background-color: {ACCENT};
            color: {ACCENT_INK};
            border: none;
            font-weight: 600;
            outline: none;
        }}
        QPushButton.primary-btn:hover {{
            background-color: #ffe066;
        }}
        QPushButton.primary-btn:pressed {{
            background-color: #e6bd19;
        }}
        QPushButton.primary-btn:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        QPushButton.secondary-btn {{
            background-color: {SURFACE2};
            color: {TEXT};
            border: 1px solid {LINE};
            font-weight: 500;
            outline: none;
        }}
        QPushButton.secondary-btn:hover {{
            background-color: #272533;
            border-color: rgba(255, 255, 255, 0.15);
        }}
        QPushButton.secondary-btn:pressed {{
            background-color: #1f1e29;
        }}
        QPushButton.secondary-btn:disabled {{
            background-color: #121118;
            color: {DIM};
            border-color: rgba(255, 255, 255, 0.03);
        }}
        QPushButton.secondary-btn:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        QPushButton.icon-btn {{
            background-color: {SURFACE2};
            border: 1px solid {LINE};
            border-radius: 10px;
            padding: 0px;
            outline: none;
        }}
        QPushButton.icon-btn:hover {{
            background-color: #272533;
            border-color: rgba(255, 255, 255, 0.18);
        }}
        QPushButton.icon-btn:pressed {{
            background-color: #1e1d28;
        }}
        QPushButton.icon-btn:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        QPushButton.ghost-btn {{
            background: transparent;
            color: {MUTED};
            border: none;
            padding: 6px 10px;
            font-weight: 500;
            outline: none;
        }}
        QPushButton.ghost-btn:hover {{
            color: {TEXT};
            background-color: rgba(255, 255, 255, 0.05);
        }}
        QPushButton.ghost-btn:pressed {{
            background-color: rgba(255, 255, 255, 0.08);
        }}
        QPushButton.ghost-btn:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        QPushButton.collapse-btn {{
            background: transparent;
            color: {TEXT};
            border: none;
            font-size: 14px;
            font-weight: 600;
            text-align: left;
            padding: 4px;
            outline: none;
        }}
        QPushButton.collapse-btn:hover {{
            color: {ACCENT};
        }}
        QPushButton.collapse-btn:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        /* Log PlainTextEdit */
        QPlainTextEdit {{
            background-color: #0a090e;
            color: {TEXT};
            border: 1px solid {LINE};
            border-radius: 10px;
            font-family: '{MONO_FONT_FAMILY}';
            font-size: 12.5px;
            font-weight: 400;
            padding: 10px;
            outline: none;
        }}
        QPlainTextEdit:focus {{
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        /* Scrollbars */
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: #2b2938;
            min-height: 24px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #3e3b4f;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        /* Context Menu */
        QMenu {{
            background-color: {SURFACE};
            color: {TEXT};
            border: 1px solid {LINE};
            border-radius: 10px;
            padding: 6px;
            font-family: '{UI_FONT_FAMILY}';
            font-size: 13px;
            font-weight: 500;
        }}
        QMenu::item {{
            padding: 7px 18px 7px 14px;
            border-radius: 6px;
        }}
        QMenu::item:selected {{
            background-color: {ACCENT};
            color: {ACCENT_INK};
            font-weight: 600;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {LINE};
            margin: 4px 6px;
        }}

        /* Dynamic IP Card States */
        QFrame#CardIP[state="ok"] {{
            background-color: rgba(61, 220, 151, 0.06);
            border: 1px solid rgba(61, 220, 151, 0.25);
        }}
        QFrame#CardIP[state="warn"] {{
            background-color: rgba(255, 107, 107, 0.06);
            border: 1px solid rgba(255, 107, 107, 0.25);
        }}
        QFrame#CardIP[state="checking"] {{
            background-color: {SURFACE};
            border: 1px solid {LINE};
        }}
        QFrame#CardIP[state="unknown"] {{
            background-color: {SURFACE};
            border: 1px solid {LINE};
        }}
    """
