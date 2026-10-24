"""Custom UI widgets for YMusic Discord RPC: AmbientBackground, CoverWidget, StatusLine, DiscordBadge, AnimatedToggleSwitch, ClickableLabel."""

import math
from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
    QLabel,
    QWidget,
)

import ui_theme


class SmoothAnimator:
    """High-frequency smooth animator synchronized with monitor refresh rate."""
    def __init__(self, duration_ms: int = 180, easing=QEasingCurve.Type.InOutCubic):
        self.duration_ms = duration_ms
        self.start_val = 0.0
        self.end_val = 0.0
        self.current_val = 0.0
        self.callback = None
        self.on_finished = None
        self.clock = QElapsedTimer()
        self.curve = QEasingCurve(easing)

        from PyQt6.QtCore import QTimer
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(7)  # ~144 FPS
        self.timer.timeout.connect(self._step)

    def is_running(self) -> bool:
        return self.timer.isActive()

    def start(self, start_val: float, end_val: float, callback, on_finished=None):
        self.timer.stop()
        self.start_val = float(start_val)
        self.end_val = float(end_val)
        self.current_val = float(start_val)
        self.callback = callback
        self.on_finished = on_finished
        self.clock.restart()
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def _step(self):
        elapsed = self.clock.elapsed()
        if elapsed >= self.duration_ms:
            self.timer.stop()
            self.current_val = self.end_val
            if self.callback:
                self.callback(1.0, self.end_val)
            if self.on_finished:
                self.on_finished()
            return
        t = elapsed / self.duration_ms
        progress = self.curve.valueForProgress(t)
        self.current_val = self.start_val + (self.end_val - self.start_val) * progress
        if self.callback:
            self.callback(progress, self.current_val)


# ---------------------------------------------------------
# Dominant Color Extraction from QImage
# ---------------------------------------------------------
def extract_dominant_accent(image: QImage) -> QColor:
    """Extract a vibrant, readable accent color from album art QImage."""
    if image.isNull() or image.width() < 1:
        return QColor(ui_theme.ACCENT)

    small = image.scaled(
        32, 32,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    candidates = []
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, s, v, _ = c.getHsv()
            # Ignore near-black, near-white, or very desaturated grey pixels
            if v < 40 or v > 240 or s < 45:
                continue
            candidates.append((s * v, c))

    if not candidates:
        return QColor(ui_theme.ACCENT)

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_color = candidates[0][1]

    # Normalize lightness/value for pleasant dark ambient glow
    h, s, v, _ = best_color.getHsv()
    v = max(110, min(v, 210))
    s = max(100, min(s, 230))
    res = QColor()
    res.setHsv(h, s, v)
    return res


# ---------------------------------------------------------
# 1. AmbientBackground Widget
# ---------------------------------------------------------
class AmbientBackground(QWidget):
    """Window container that paints BG and a soft radial ambient gradient from top-left.
    Renders from pre-baked QPixmap cache to eliminate frame stutter during UI animations.
    Glow geometry is strictly constant (radius = 480.0) so window height changes do not
    shift, scale, or pop the ambient glow halo.
    """
    GLOW_RADIUS = 480.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CentralWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self._current_r = 255.0
        self._current_g = 210.0
        self._current_b = 31.0
        self._current_alpha = 0.08  # Default subtle accent glow

        self._target_r = 255.0
        self._target_g = 210.0
        self._target_b = 31.0
        self._target_alpha = 0.08

        self._start_r = self._current_r
        self._start_g = self._current_g
        self._start_b = self._current_b
        self._start_alpha = self._current_alpha

        self._anim = SmoothAnimator(duration_ms=400)
        self._cached_pixmap = None

    def _render_cache(self):
        w = max(10, self.width())
        h = max(10, self.height())
        dpr = self.devicePixelRatio()
        scaled_w = int(w * dpr)
        scaled_h = int(h * dpr)

        pix = QPixmap(scaled_w, scaled_h)
        pix.setDevicePixelRatio(dpr)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Fill base dark background
        painter.fillRect(QRect(0, 0, w, h), QColor(ui_theme.BG))

        # 2. Radial gradient from top-left corner with fixed radius
        gradient = QRadialGradient(0.0, 0.0, self.GLOW_RADIUS, 0.0, 0.0)
        c_glow = QColor(
            int(self._current_r),
            int(self._current_g),
            int(self._current_b),
            int(255 * self._current_alpha),
        )
        c_fade = QColor(
            int(self._current_r),
            int(self._current_g),
            int(self._current_b),
            0,
        )
        gradient.setColorAt(0.0, c_glow)
        gradient.setColorAt(0.65, QColor(int(self._current_r), int(self._current_g), int(self._current_b), int(255 * self._current_alpha * 0.2)))
        gradient.setColorAt(1.0, c_fade)

        painter.fillRect(QRect(0, 0, w, h), QBrush(gradient))
        painter.end()
        self._cached_pixmap = pix

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize() != event.size():
            self._render_cache()

    def set_glow_color(self, color: QColor, has_cover: bool = True):
        self._start_r = self._current_r
        self._start_g = self._current_g
        self._start_b = self._current_b
        self._start_alpha = self._current_alpha

        self._target_r = float(color.red())
        self._target_g = float(color.green())
        self._target_b = float(color.blue())
        self._target_alpha = 0.28 if has_cover else 0.08

        def on_step(progress, _val):
            self._current_r = self._start_r + (self._target_r - self._start_r) * progress
            self._current_g = self._start_g + (self._target_g - self._start_g) * progress
            self._current_b = self._start_b + (self._target_b - self._start_b) * progress
            self._current_alpha = self._start_alpha + (self._target_alpha - self._start_alpha) * progress
            self._render_cache()
            self.update()

        self._anim.start(0.0, 1.0, on_step)

    def reset_glow(self):
        accent = QColor(ui_theme.ACCENT)
        self.set_glow_color(accent, has_cover=False)

    def paintEvent(self, event):
        if not self._cached_pixmap or self._cached_pixmap.isNull():
            self._render_cache()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cached_pixmap)
        painter.end()


# ---------------------------------------------------------
# 2. CoverWidget (116x116)
# ---------------------------------------------------------
class CoverWidget(QWidget):
    """Square album cover with 16px rounded corners and cached pixmap rendering.
    Avoids QGraphicsDropShadowEffect to maintain smooth 60-144+ FPS animation rates.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(116, 116)
        self._pixmap = None
        self._dominant_color = None
        self._cached_pixmap = None
        self._rebuild_cache()

    def _rebuild_cache(self):
        dpr = self.devicePixelRatio()
        w = self.width()
        h = self.height()
        scaled_w = int(w * dpr)
        scaled_h = int(h * dpr)

        pix = QPixmap(scaled_w, scaled_h)
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        if self._pixmap and not self._pixmap.isNull():
            painter.save()
            painter.setClipPath(path)
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (w - scaled.width()) // 2
            sy = (h - scaled.height()) // 2
            painter.drawPixmap(sx, sy, scaled)
            painter.restore()

            # Thin inner border: rgba(255,255,255,0.12)
            painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            # Placeholder: SURFACE2 with LINE border & centered app_icon.svg
            painter.fillPath(path, QBrush(QColor(ui_theme.SURFACE2)))
            painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
            painter.drawPath(path)

            icon_pix = ui_theme.svg_pixmap("app_icon", 56)
            if not icon_pix.isNull():
                painter.setOpacity(0.9)
                ix = (w - 56) // 2
                iy = (h - 56) // 2
                painter.drawPixmap(ix, iy, icon_pix)

        painter.end()
        self._cached_pixmap = pix

    def set_cover_pixmap(self, pixmap: QPixmap | None, dominant_color: QColor | None = None):
        self._pixmap = pixmap
        self._dominant_color = dominant_color
        self._rebuild_cache()
        self.update()

    def paintEvent(self, event):
        if not self._cached_pixmap or self._cached_pixmap.isNull():
            self._rebuild_cache()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cached_pixmap)
        painter.end()


# ---------------------------------------------------------
# 3. StatusLine Widget (Icon + Text via QPainter)
# ---------------------------------------------------------
class StatusLine(QWidget):
    """Paints status icon (play gradient triangle / pause bars / idle ring) + label with zero emojis."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"  # "playing" | "paused" | "idle"
        self.setFixedHeight(22)

    def set_state(self, state: str):
        if state in ("playing", "paused", "idle") and state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        icon_size = 16
        y_top = (self.height() - icon_size) / 2.0
        text_x = 24.0

        if self.state == "playing":
            # Gradient triangle points: (5.5, 3.6), (12.0, 8.0), (5.5, 12.4)
            poly_path = QPainterPath()
            poly_path.moveTo(5.5, y_top + 3.6)
            poly_path.lineTo(12.0, y_top + 8.0)
            poly_path.lineTo(5.5, y_top + 12.4)
            poly_path.closeSubpath()

            grad = QLinearGradient(4, y_top + 3, 13, y_top + 13)
            grad.setColorAt(0.0, QColor("#8cf5c0"))
            grad.setColorAt(1.0, QColor(ui_theme.OK))

            # Subtle glow behind triangle
            glow_pen = QPen(QColor(61, 220, 151, 60), 4)
            glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(glow_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(poly_path)

            # Filled rounded stroke triangle
            pen = QPen(QBrush(grad), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(poly_path)

            # Text
            painter.setFont(ui_theme.font_ui(12, QFont.Weight.Medium))
            painter.setPen(QColor(ui_theme.OK))
            painter.drawText(int(text_x), int(y_top + 12.5), "Воспроизводится")

        elif self.state == "paused":
            # Two rounded vertical bars: (4.5, 3.5, 2.6, 9.0) and (8.9, 3.5, 2.6, 9.0), radius 1.3
            grad = QLinearGradient(4, y_top + 3, 13, y_top + 13)
            grad.setColorAt(0.0, QColor("#8cf5c0"))
            grad.setColorAt(1.0, QColor(ui_theme.OK))

            painter.save()
            painter.setOpacity(0.65)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(QRectF(4.5, y_top + 3.5, 2.6, 9.0), 1.3, 1.3)
            painter.drawRoundedRect(QRectF(8.9, y_top + 3.5, 2.6, 9.0), 1.3, 1.3)
            painter.restore()

            # Text
            painter.setFont(ui_theme.font_ui(12, QFont.Weight.Medium))
            painter.setPen(QColor(ui_theme.MUTED))
            painter.drawText(int(text_x), int(y_top + 12.5), "На паузе")

        else:  # idle
            # Thin ring: circle center (8.0, y_top + 8.0), r=5.2, pen 1.6, DIM
            painter.setPen(QPen(QColor(ui_theme.DIM), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(8.0, y_top + 8.0), 5.2, 5.2)

            # Text
            painter.setFont(ui_theme.font_ui(12, QFont.Weight.Medium))
            painter.setPen(QColor(ui_theme.DIM))
            painter.drawText(int(text_x), int(y_top + 12.5), "Ожидание воспроизведения")

        painter.end()


# ---------------------------------------------------------
# 4. DiscordBadge Widget (Pill)
# ---------------------------------------------------------
class DiscordBadge(QWidget):
    """Pill badge with Discord logo, status dot indicator, and connection label."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected: bool | None = None  # None = initial connecting, True = connected, False = searching
        self._text = "Подключаюсь…"
        self._pulse_alpha = 1.0
        self._pulse_dir = -1
        self.setFixedHeight(32)
        self.setFont(ui_theme.font_ui(13, QFont.Weight.Medium))
        self._update_size()

        # Pulse timer for searching/connecting indicator
        from PyQt6.QtCore import QTimer
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(45)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_timer.start()

    def _update_size(self):
        font = ui_theme.font_ui(13, QFont.Weight.Medium)
        fm = self.fontMetrics() if self.fontMetrics() else QFontMetrics(font)
        text_width = fm.horizontalAdvance(self._text)
        total_w = 12 + 16 + 8 + text_width + 16  # margins + icon + gap + text + right padding
        self.setFixedSize(total_w, 32)
        self.updateGeometry()

    def set_status(self, connected: bool):
        self.connected = connected
        if connected:
            self._text = "Discord подключён"
            self._pulse_timer.stop()
            self._pulse_alpha = 1.0
        else:
            self._text = "Поиск Discord…"
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        self._update_size()
        self.update()

    def _on_pulse(self):
        if self.connected is True:
            return
        self._pulse_alpha += self._pulse_dir * 0.04
        if self._pulse_alpha <= 0.35:
            self._pulse_alpha = 0.35
            self._pulse_dir = 1
        elif self._pulse_alpha >= 1.0:
            self._pulse_alpha = 1.0
            self._pulse_dir = -1
        self.update()

    def sizeHint(self) -> QSize:
        font = ui_theme.font_ui(13, QFont.Weight.Medium)
        fm = self.fontMetrics() if self.fontMetrics() else QFontMetrics(font)
        text_width = fm.horizontalAdvance(self._text)
        total_w = 12 + 16 + 8 + text_width + 16
        return QSize(total_w, 32)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Pill Background: rgba(255,255,255,0.06), border: LINE
        w = self.width()
        h = self.height()
        pill_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill_rect, 16, 16)

        painter.fillPath(pill_path, QColor(255, 255, 255, 15))
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawPath(pill_path)

        # 2. Discord SVG Icon 16x16 at x=12, y=8
        icon_color = ui_theme.DISCORD if self.connected else ui_theme.DIM
        dpr = self.devicePixelRatio()
        icon_pix = ui_theme.svg_pixmap("discord", 16, icon_color, dpr=dpr)
        painter.drawPixmap(12, 8, icon_pix)

        # 3. Status dot indicator (7px with 2px background stroke) at bottom-right of icon
        dot_center = QPointF(24.5, 20.5)
        dot_color = QColor(ui_theme.OK if self.connected else ui_theme.WARN)
        if not self.connected:
            dot_color.setAlpha(int(255 * self._pulse_alpha))

        # Stroke to separate from icon
        painter.setPen(QPen(QColor(ui_theme.SURFACE), 2))
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(dot_center, 3.5, 3.5)

        # 4. Label text
        painter.setFont(ui_theme.font_ui(13, QFont.Weight.Medium))
        painter.setPen(QColor(ui_theme.TEXT))
        painter.drawText(QRectF(36, 0, w - 46, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)

        painter.end()



# ---------------------------------------------------------
# 5. AnimatedToggleSwitch Widget (46x28, ACCENT yellow)
# ---------------------------------------------------------
class AnimatedToggleSwitch(QCheckBox):
    """Modern smooth animated toggle switch (46x28) with single yellow ACCENT color."""
    def __init__(self, parent=None, checked=True, active_color=ui_theme.ACCENT):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 28)
        self._circle_position = 28.0 if checked else 6.0
        self._anim = SmoothAnimator(duration_ms=180)
        self.toggled.connect(self._on_toggled)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def _on_toggled(self, checked: bool):
        target = 28.0 if checked else 6.0
        self._anim.start(self._circle_position, target, self._on_anim_step)

    def _on_anim_step(self, _progress, val):
        self._circle_position = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        track_rect = QRectF(1, 2, 44, 24)
        if self.isChecked():
            painter.setBrush(QBrush(QColor(ui_theme.ACCENT)))
            painter.drawRoundedRect(track_rect, 12, 12)
            # Inner circle (ACCENT_INK)
            painter.setBrush(QBrush(QColor(ui_theme.ACCENT_INK)))
            painter.drawEllipse(QRectF(self._circle_position - 3, 5, 18, 18))
        else:
            painter.setBrush(QBrush(QColor("#3a3946")))
            painter.drawRoundedRect(track_rect, 12, 12)
            # Inner circle (White)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawEllipse(QRectF(self._circle_position - 3, 5, 18, 18))

        if self.hasFocus():
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track_rect.adjusted(-1, -1, 1, 1), 13, 13)

        painter.end()


# ---------------------------------------------------------
# 6. ClickableLabel Widget
# ---------------------------------------------------------
class ClickableLabel(QLabel):
    """QLabel emitting clicked signal on mouse release."""
    clicked = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------
# 7. Elided Labels for Track Meta
# ---------------------------------------------------------
class ElidedTitleLabel(QLabel):
    """Word-wrapping title label that renders up to 2 lines and elides overflow with ellipsis."""
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setFont(ui_theme.font_ui(16, QFont.Weight.DemiBold))
        self.setFixedHeight(54)
        self.setToolTip(text)

    def setText(self, text: str):
        self._full_text = text
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._full_text

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        painter.setPen(QColor(ui_theme.TEXT))

        fm = painter.fontMetrics()
        line_height = fm.lineSpacing()
        avail_w = self.width()

        words = self._full_text.split()
        if not words:
            painter.end()
            return

        # Check if entire text fits on 1 line
        if fm.horizontalAdvance(self._full_text) <= avail_w:
            y = fm.ascent() + (self.height() - fm.height()) // 2
            painter.drawText(0, y, self._full_text)
            painter.end()
            return

        # Build Line 1
        line1_words = []
        idx = 0
        while idx < len(words):
            test_str = " ".join(line1_words + [words[idx]])
            if fm.horizontalAdvance(test_str) <= avail_w:
                line1_words.append(words[idx])
                idx += 1
            else:
                break

        if not line1_words and idx < len(words):
            line1_words.append(words[idx])
            idx += 1

        line1 = " ".join(line1_words)

        # Build Line 2 (elided if remaining text overflows)
        rem_text = " ".join(words[idx:])
        line2 = fm.elidedText(rem_text, Qt.TextElideMode.ElideRight, avail_w)

        y1 = fm.ascent() + 2
        y2 = y1 + line_height
        painter.drawText(0, y1, line1)
        if line2:
            painter.drawText(0, y2, line2)

        painter.end()


class ElidedArtistLabel(QLabel):
    """Single-line artist label that cleanly elides text on overflow."""
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setFont(ui_theme.font_ui(11.5, QFont.Weight.Normal))
        self.setFixedHeight(22)
        self.setToolTip(text)

    def setText(self, text: str):
        self._full_text = text
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._full_text

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        painter.setPen(QColor(ui_theme.MUTED))

        fm = painter.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(0, fm.ascent() + 2, elided)
        painter.end()


# ---------------------------------------------------------
# 8. RevealPanel Widget (Clipping wrapper for animated panels)
# ---------------------------------------------------------
class RevealPanel(QWidget):
    """Clipping container for animated panels without internal layout reflows during animation.
    The child content widget is positioned manually at (0, 0, width, content_height)
    and clipped by RevealPanel rect.
    """
    def __init__(self, content: QWidget, content_height: int = 240, parent=None):
        super().__init__(parent)
        self._content = content
        self._content_height = content_height
        if self._content:
            self._content.setParent(self)
            self._content.setFixedHeight(content_height)
            self._content.setGeometry(0, 0, self.width(), self._content_height)
        self.setFixedHeight(0)
        self.setVisible(False)

    @property
    def content(self) -> QWidget:
        return self._content

    @property
    def content_height(self) -> int:
        return self._content_height

    def set_content_height(self, h: int):
        self._content_height = h
        if self._content:
            self._content.setGeometry(0, 0, self.width(), self._content_height)

    def set_reveal_height(self, h: int):
        self.setFixedHeight(max(0, int(h)))
        if self._content:
            self._content.setGeometry(0, 0, self.width(), self._content_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._content:
            self._content.setGeometry(0, 0, self.width(), self._content_height)


