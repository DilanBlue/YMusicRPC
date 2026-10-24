"""Preview tool for capturing visual states of MainWindow without running background workers."""

import os
import sys
import time

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

import app
import ui_theme


def create_sample_cover(color_hex="#ff5588", size=300) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(color_hex))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(255, 255, 255, 50))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(size * 0.2), int(size * 0.2), int(size * 0.6), int(size * 0.6))
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawEllipse(int(size * 0.4), int(size * 0.4), int(size * 0.2), int(size * 0.2))
    p.end()
    return pix


def run_preview():
    preview_dir = os.path.join(PROJECT_ROOT, "preview")
    os.makedirs(preview_dir, exist_ok=True)

    qapp = QApplication(sys.argv)
    ui_theme.init_fonts()

    window = app.MainWindow(start_minimized=False)
    # Immediately stop background worker to take full programmatic control
    if hasattr(window, "worker"):
        window.worker.stop()
    if hasattr(window, "ip_thread") and window.ip_thread:
        window.ip_thread.terminate()

    # Dismiss splash overlay immediately for snapshot generation
    if window.loading_overlay:
        window.loading_overlay.hide()
        window.loading_overlay.timer.stop()

    window.show()
    qapp.processEvents()

    # State 1: Idle (music not playing, searching Discord, checking IP)
    window.on_no_track()
    window.on_discord_status(False)
    window.on_ip_checked("", "", False)
    qapp.processEvents()
    time.sleep(0.05)
    window.grab().save(os.path.join(preview_dir, "1_idle.png"))
    print("Saved 1_idle.png")

    # State 2: Playing (regular track, cover loaded, Discord connected, IP RU)
    sample_pix = create_sample_cover("#8c52ff")
    window.on_discord_status(True)
    window.on_ip_checked("185.12.34.56", "RU", True)
    window.track_title.setText("TWENTY")
    window.track_artist.setText("lightprey")
    window.status_line.set_state("playing")
    dom_color = QColor("#8c52ff")
    window.cover_widget.set_cover_pixmap(sample_pix, dom_color)
    window.centralWidget().set_glow_color(dom_color, has_cover=True)
    qapp.processEvents()
    time.sleep(0.05)
    window.grab().save(os.path.join(preview_dir, "2_playing.png"))
    print("Saved 2_playing.png")

    # State 3: Playing with long title (testing 2-line wrap & typography)
    window.track_title.setText("Очень длинное название музыкальной композиции для проверки переноса")
    window.track_artist.setText("Исполнитель с очень длинным и красивым сценическим псевдонимом")
    qapp.processEvents()
    time.sleep(0.05)
    window.grab().save(os.path.join(preview_dir, "3_playing_long_title.png"))
    print("Saved 3_playing_long_title.png")

    # State 4: Paused
    window.status_line.set_state("paused")
    qapp.processEvents()
    time.sleep(0.05)
    window.grab().save(os.path.join(preview_dir, "4_paused.png"))
    print("Saved 4_paused.png")

    # State 5: Foreign IP (VPN Warning Banner)
    window.on_ip_checked("89.160.20.15", "DE", False)
    qapp.processEvents()
    time.sleep(0.05)
    window.grab().save(os.path.join(preview_dir, "5_warn_vpn.png"))
    print("Saved 5_warn_vpn.png")

    # State 6: Log expanded
    window.append_log("Фоновый процесс запущен")
    window.append_log("Трек: lightprey — TWENTY")
    window.append_log("Обложка трека успешно загружена")
    window.toggle_log_view()
    # Let animation complete
    for _ in range(35):
        qapp.processEvents()
        time.sleep(0.01)
    window.grab().save(os.path.join(preview_dir, "6_log_expanded.png"))
    print("Saved 6_log_expanded.png")

    print(f"All previews successfully generated in: {preview_dir}")
    window.close()


if __name__ == "__main__":
    run_preview()
