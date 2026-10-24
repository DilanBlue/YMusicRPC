import asyncio
import ctypes
import html
import math
import os
import sys
import threading
import time
import winreg
import requests

try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    QThread,
    QTimer,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

import ui_theme
from ui_widgets import (
    AmbientBackground,
    CoverWidget,
    StatusLine,
    DiscordBadge,
    AnimatedToggleSwitch,
    ClickableLabel,
    extract_dominant_accent,
    ElidedTitleLabel,
    ElidedArtistLabel,
    RevealPanel,
)



import pypresence
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
)

CLIENT_ID = "1536782293438435491"
POLL_INTERVAL_SECONDS = 2
DISCORD_RECONNECT_INTERVAL_SECONDS = 5
TARGET_APP_ID_HINT = "yandex"
PLAYBACK_STATUS_PLAYING = 4
YANDEX_LARGE_TEXT = "Яндекс Музыка"
DEFAULT_FALLBACK_ASSET = "yandex_music_logo"

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VAL_NAME = "YMusicDiscordRPC"
LOCAL_SERVER_NAME = "YMusicDiscordRPC_SingleInstance_Key"

APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
LOG_PATH = os.path.join(APP_DIR, "log.txt")
MAX_LOG_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB limit for log rotation


def log(message):
    try:
        # Simple log rotation if log file grows beyond limit
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_SIZE_BYTES:
            try:
                with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-2000:]
                with open(LOG_PATH, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except Exception:
                pass

        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def get_target_exe():
    if getattr(sys, "frozen", False):
        return sys.executable
    exe_candidate = os.path.join(APP_DIR, "YMusicRPC.exe")
    if os.path.exists(exe_candidate):
        return exe_candidate
    return sys.executable


def get_real_desktop_path():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        expanded = os.path.expandvars(val)
        if os.path.exists(expanded):
            return expanded
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def get_startup_shortcut_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    startup_dir = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
    return os.path.join(startup_dir, "YMusicRPC.lnk")


def is_autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, REG_VAL_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    target_exe = get_target_exe()
    lnk_path = get_startup_shortcut_path()

    # Clean up any leftover shortcut from Startup folder to prevent double-boot
    try:
        if os.path.exists(lnk_path):
            os.remove(lnk_path)
    except Exception:
        pass

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_KEY,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_READ,
        )
        if enable:
            if getattr(sys, "frozen", False) or target_exe.endswith(".exe"):
                cmd = f'"{target_exe}" --minimized'
            else:
                cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}" --minimized'
            winreg.SetValueEx(key, REG_VAL_NAME, 0, winreg.REG_SZ, cmd)
            log("Autostart enabled in Windows Registry (single instance)")
        else:
            try:
                winreg.DeleteValue(key, REG_VAL_NAME)
                log("Autostart disabled in Windows Registry")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        log(f"Registry autostart management failed: {e}")

    return is_autostart_enabled() == enable


# In-memory cover cache to avoid redundant API queries
_COVER_URL_CACHE = {}
_COVER_CACHE_LOCK = threading.Lock()


def fetch_cover_url(title, artist):
    query = f"{artist} {title}".strip()
    if not query:
        return None

    with _COVER_CACHE_LOCK:
        if query in _COVER_URL_CACHE:
            return _COVER_URL_CACHE[query]

    try:
        resp = requests.get(
            "https://api.music.yandex.net/search",
            params={"text": query, "type": "track", "page": 0},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            },
            timeout=3,
        )
        if resp.status_code == 451:
            log(f"Cover fetch 451: Legal restriction / Non-RU IP for '{query}'")
            return None
        resp.raise_for_status()
        data = resp.json()
        tracks = data.get("result", {}).get("tracks", {}).get("results", [])
        if tracks:
            cover_uri = tracks[0].get("coverUri")
            if cover_uri:
                url = cover_uri.replace("%%", "600x600")
                if not url.startswith("http"):
                    url = "https://" + url
                with _COVER_CACHE_LOCK:
                    if len(_COVER_URL_CACHE) > 200:
                        _COVER_URL_CACHE.clear()
                    _COVER_URL_CACHE[query] = url
                return url
    except Exception as e:
        log(f"Cover fetch failed: {e}")
    return None


class CoverArtCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self.cover_url = None

    def start_new_track(self, title, artist, callback=None):
        with self._lock:
            self._version += 1
            version = self._version
            self.cover_url = None
        threading.Thread(
            target=self._fetch, args=(title, artist, version, callback), daemon=True
        ).start()

    def _fetch(self, title, artist, version, callback):
        url = fetch_cover_url(title, artist)
        with self._lock:
            if version == self._version:
                self.cover_url = url
                if callback:
                    callback(url)


class MediaSessionHolder:
    """Reuses MediaManager COM session manager across calls to prevent handle leaks."""
    def __init__(self):
        self._manager = None

    async def get_manager(self):
        if self._manager is None:
            self._manager = await MediaManager.request_async()
        return self._manager

    def reset(self):
        self._manager = None


_SESSION_HOLDER = MediaSessionHolder()


async def get_active_track():
    try:
        manager = await _SESSION_HOLDER.get_manager()
        sessions = manager.get_sessions()
    except Exception:
        _SESSION_HOLDER.reset()
        manager = await _SESSION_HOLDER.get_manager()
        sessions = manager.get_sessions()

    yandex_session = None
    for session in sessions:
        app_id = (session.source_app_user_model_id or "").lower()
        if TARGET_APP_ID_HINT in app_id:
            yandex_session = session
            break

    if yandex_session is None:
        return None

    props = await yandex_session.try_get_media_properties_async()
    playback_info = yandex_session.get_playback_info()
    is_playing = playback_info.playback_status == PLAYBACK_STATUS_PLAYING

    title = (props.title or "").strip()
    artist = (props.artist or "").strip()

    if not title or not artist:
        return None

    return title, artist, is_playing


def poll_yandex_track(loop):
    try:
        return loop.run_until_complete(get_active_track())
    except Exception as e:
        log(f"Yandex SMTC read error: {e}")
        return None


class DiscordRPCManager:
    def __init__(self, client_id, reconnect_interval):
        self.client_id = client_id
        self.reconnect_interval = reconnect_interval
        self.rpc = None
        self.connected = False
        self._next_attempt_at = 0.0

    def _reset(self):
        old_rpc = self.rpc
        self.rpc = None
        self.connected = False
        if old_rpc is not None:
            try:
                old_rpc.close()
            except Exception:
                pass

    def try_connect(self, force=False):
        now = time.time()
        if not force and now < self._next_attempt_at:
            return False
        self._next_attempt_at = now + self.reconnect_interval

        candidate = pypresence.Presence(self.client_id)
        try:
            candidate.connect()
        except Exception:
            self._reset()
            return False

        self.rpc = candidate
        self.connected = True
        return True

    def update(self, **kwargs):
        if not self.connected or self.rpc is None:
            return False
        try:
            self.rpc.update(**kwargs)
            return True
        except Exception as e:
            log(f"Discord update failed: {e}")
            self._reset()
            return False

    def clear(self):
        if not self.connected or self.rpc is None:
            return False
        try:
            self.rpc.clear()
            return True
        except Exception:
            self._reset()
            return False

    def shutdown(self):
        if self.rpc is not None and self.connected:
            try:
                self.rpc.clear()
            except Exception:
                pass
        if self.rpc is not None:
            try:
                self.rpc.close()
            except Exception:
                pass
        self.rpc = None
        self.connected = False


class RPCWorker(QThread):
    sig_track_update = pyqtSignal(str, str, bool, object)
    sig_no_track = pyqtSignal()
    sig_discord_status = pyqtSignal(bool)
    sig_log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.rpc_enabled = True
        self.discord = DiscordRPCManager(CLIENT_ID, DISCORD_RECONNECT_INTERVAL_SECONDS)
        self.cover_cache = CoverArtCache()
        self._loop = None

    def set_rpc_enabled(self, enabled: bool):
        self.rpc_enabled = enabled
        if not enabled:
            self.discord.clear()
            self.sig_log.emit("Функция RPC отключена (статус в Discord очищен)")
            log("RPC disabled by user")
        else:
            self.sig_log.emit("Функция RPC включена")
            log("RPC enabled by user")

    def stop(self):
        self.running = False
        self.wait(1500)

    def run(self):
        self._loop = asyncio.new_event_loop()
        log("Background RPC worker started")
        self.sig_log.emit("Запуск мониторинга Яндекс Музыки...")

        if self.discord.try_connect(force=True):
            self.sig_discord_status.emit(True)
            self.sig_log.emit("Discord успешно подключен")
            log("Discord connected at startup")
        else:
            self.sig_discord_status.emit(False)
            self.sig_log.emit("Discord не найден, автопоиск в фоне...")
            log("Discord not found at startup")

        last_track = None
        last_is_playing = None
        last_sent_cover_url = None
        start_timestamp = None
        need_presence_resend = False

        initial_poll_done = False

        while self.running:
            try:
                was_connected = self.discord.connected
                if not self.discord.connected:
                    if self.discord.try_connect():
                        self.sig_discord_status.emit(True)
                        self.sig_log.emit("Discord подключен!")
                        need_presence_resend = True
                elif not was_connected and self.discord.connected:
                    self.sig_discord_status.emit(True)
                    need_presence_resend = True

                track = poll_yandex_track(self._loop)

                if not initial_poll_done:
                    initial_poll_done = True
                    if track is None:
                        self.sig_no_track.emit()

                if track is None:
                    if last_track is not None:
                        if self.rpc_enabled:
                            cleared = self.discord.clear()
                            if cleared:
                                self.sig_log.emit("Музыка остановлена — статус очищен")
                        last_track = None
                        last_is_playing = None
                        last_sent_cover_url = None
                        self.sig_no_track.emit()
                    # Responsive sleep
                    for _ in range(POLL_INTERVAL_SECONDS * 10):
                        if not self.running:
                            break
                        time.sleep(0.1)
                    continue

                title, artist, is_playing = track
                current_track = (title, artist)
                track_changed = current_track != last_track
                play_state_changed = is_playing != last_is_playing

                if track_changed:
                    start_timestamp = int(time.time())
                    last_sent_cover_url = None
                    self.sig_log.emit(f"Трек: {artist} — {title}")
                    log(f"Yandex track: {artist} - {title}")

                    def on_cover_found(url):
                        # Only update if still same track
                        if current_track == last_track:
                            self.sig_track_update.emit(title, artist, is_playing, url)
                            if url:
                                self.sig_log.emit("Обложка трека успешно загружена")

                    self.cover_cache.start_new_track(title, artist, callback=on_cover_found)

                # Reset start timestamp on resume from pause
                if play_state_changed and is_playing and not track_changed:
                    start_timestamp = int(time.time())

                cover_url = self.cover_cache.cover_url
                cover_just_arrived = (
                    cover_url is not None and cover_url != last_sent_cover_url
                )

                # Only emit track update when something actually changed to avoid UI re-rendering churn
                if track_changed or play_state_changed or cover_just_arrived:
                    self.sig_track_update.emit(title, artist, is_playing, cover_url)

                if self.rpc_enabled and (
                    track_changed or play_state_changed or need_presence_resend or cover_just_arrived
                ):
                    image_kwargs = {"large_image": cover_url} if cover_url else {"large_image": DEFAULT_FALLBACK_ASSET}
                    if is_playing:
                        ok = self.discord.update(
                            details=title,
                            state=artist or YANDEX_LARGE_TEXT,
                            large_text=YANDEX_LARGE_TEXT,
                            start=start_timestamp,
                            **image_kwargs,
                        )
                    else:
                        ok = self.discord.update(
                            details=title,
                            state=f"{artist} (на паузе)" if artist else "На паузе",
                            large_text=YANDEX_LARGE_TEXT,
                            **image_kwargs,
                        )

                    if ok:
                        need_presence_resend = False
                        last_sent_cover_url = cover_url
                    else:
                        self.sig_discord_status.emit(False)

                last_track = current_track
                last_is_playing = is_playing

            except Exception as e:
                log(f"Worker loop exception: {e}")

            # Responsive interruptible sleep
            for _ in range(POLL_INTERVAL_SECONDS * 10):
                if not self.running:
                    break
                time.sleep(0.1)

        self.discord.shutdown()
        if self._loop:
            self._loop.close()
        log("Background RPC worker terminated")


class IPCheckerThread(QThread):
    sig_result = pyqtSignal(str, str, bool)

    def run(self):
        services = [
            ("https://ipinfo.io/json", lambda d: (d.get("ip", ""), d.get("country", ""))),
            ("http://ip-api.com/json", lambda d: (d.get("query", ""), d.get("countryCode", ""))),
        ]
        ip, country = "", ""
        for url, parser in services:
            try:
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    ip, country = parser(resp.json())
                    if ip and country:
                        break
            except Exception:
                continue

        country = country.strip().upper()
        is_ru = (country == "RU")
        self.sig_result.emit(ip, country, is_ru)


class SmoothAnimator:
    """Adaptive high-refresh rate animator (60/144/240 Hz) using Windows multimedia precision timers."""
    def __init__(self, duration_ms=220, easing_fn=None):
        self.duration_ms = duration_ms
        self.easing_fn = easing_fn or (lambda t: 1.0 - math.pow(1.0 - t, 3))
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._step)
        self.clock = QElapsedTimer()
        self.start_val = 0.0
        self.end_val = 1.0
        self.current_val = 0.0
        self.callback = None
        self.on_finished = None
        self._update_interval()

    def _update_interval(self):
        hz = 144.0
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen and screen.refreshRate() > 30:
                hz = float(screen.refreshRate())
        self.interval_ms = max(1, int(round(1000.0 / hz)))
        self.timer.setInterval(self.interval_ms)

    def is_running(self):
        return self.timer.isActive()

    def start(self, start_val, end_val, callback, on_finished=None):
        self.timer.stop()
        self._update_interval()
        self.start_val = float(start_val)
        self.current_val = float(start_val)
        self.end_val = float(end_val)
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
        progress = self.easing_fn(t)
        self.current_val = self.start_val + (self.end_val - self.start_val) * progress
        if self.callback:
            self.callback(progress, self.current_val)


def get_app_icon_pixmap(size: int = 110) -> QPixmap:
    pix = ui_theme.svg_pixmap("app_icon", size)
    if not pix.isNull():
        return pix

    candidates = [
        os.path.join(APP_DIR, "app_icon.png"),
        os.path.join(APP_DIR, "app_icon.ico"),
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, os.path.join(meipass, "app_icon.png"))
        candidates.insert(1, os.path.join(meipass, "app_icon.ico"))

    for path in candidates:
        if os.path.exists(path):
            p = QPixmap(path)
            if not p.isNull():
                return p.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return pix



class LoadingOverlay(QWidget):
    """Full AMOLED loading splash overlay with a centered 144Hz breathing icon and smooth fade-out."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.clock = QElapsedTimer()
        self.clock.start()
        # 1100 ms per complete calm breathing pulse cycle
        self.period = 1100
        self.icon_pixmap = get_app_icon_pixmap(size=110)
        self.global_opacity = 1.0
        self.is_fading_out = False
        self.fade_anim = None

        if parent:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

        hz = 144.0
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen and screen.refreshRate() > 30:
                hz = float(screen.refreshRate())
        interval_ms = max(1, int(round(1000.0 / hz)))

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def eventFilter(self, obj, event):
        if obj == self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    def dismiss(self, on_done=None):
        if self.is_fading_out:
            return
        self.is_fading_out = True
        self.fade_anim = SmoothAnimator(duration_ms=260)

        def on_step(progress, val):
            self.global_opacity = val
            self.update()

        def on_finished():
            if self.parent():
                try:
                    self.parent().removeEventFilter(self)
                except Exception:
                    pass
            self.timer.stop()
            self.global_opacity = 0.0
            self.hide()
            if on_done:
                on_done()

        self.fade_anim.start(1.0, 0.0, on_step, on_finished)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Base background with fade-out opacity in theme BG #0c0b10
        painter.fillRect(
            self.rect(),
            QColor(12, 11, 16, int(255 * max(0.0, min(1.0, self.global_opacity)))),
        )

        if not self.icon_pixmap.isNull() and self.global_opacity > 0.01:
            elapsed = self.clock.elapsed()
            phase = (elapsed % self.period) / self.period
            # Smooth harmonic breathing: oscillates between 0.30 and 1.0
            breath_factor = 0.30 + 0.70 * ((1.0 + math.cos(2 * math.pi * phase)) / 2.0)
            final_icon_opacity = breath_factor * self.global_opacity

            painter.setOpacity(max(0.0, min(1.0, final_icon_opacity)))
            dpr = self.icon_pixmap.devicePixelRatio()
            iw = int(self.icon_pixmap.width() / dpr)
            ih = int(self.icon_pixmap.height() / dpr)
            ix = (self.width() - iw) // 2
            iy = (self.height() - ih) // 2
            painter.drawPixmap(ix, iy, self.icon_pixmap)

        painter.end()



class MainWindow(QMainWindow):
    sig_cover_ready = pyqtSignal(object, str)

    def __init__(self, start_minimized=False):
        super().__init__()
        self.setWindowTitle("YMusic Discord RPC")
        self.setFixedWidth(560)
        self._log_anim = SmoothAnimator(duration_ms=240)
        self._is_log_expanded = False

        icon_path = os.path.join(APP_DIR, "app_icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Windows 10/11 Dark Titlebar & Caption Color
        try:
            hwnd = int(self.winId())
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
            caption_color = ctypes.c_uint(0x00100b0c)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
        except Exception:
            pass

        # Privacy / IP state
        self.current_ip = ""
        self.current_country = ""
        self.is_ru = False
        self.is_ip_revealed = False
        self._current_displayed_cover_url = None
        self.ip_thread = None

        self.apply_amoled_style()
        self.init_ui()
        self.init_tray()

        # Connect thread-safe cover signal
        self.sig_cover_ready.connect(self._on_cover_image_ready)

        # Loading screen overlay (unless launched minimized in background)
        self.loading_overlay = None
        self._initial_load_complete = False
        self._initial_discord_reported = False
        self._initial_media_reported = False
        self._loading_start_time = time.time()

        if not start_minimized:
            self.loading_overlay = LoadingOverlay(self.centralWidget())
            self.loading_overlay.setGeometry(self.centralWidget().rect())
            self.loading_overlay.show()
            self.loading_overlay.raise_()
            # Fallback timeout: 2.2s (2 full breathing cycles) to guarantee dismissal
            QTimer.singleShot(2200, self._try_dismiss_loading)
        else:
            self._initial_load_complete = True

        self.worker = RPCWorker()
        self.worker.sig_track_update.connect(self.on_track_update)
        self.worker.sig_no_track.connect(self.on_no_track)
        self.worker.sig_discord_status.connect(self.on_discord_status)
        self.worker.sig_log.connect(self.append_log)
        self.worker.start()

        self.check_ip()

        if start_minimized:
            self.hide()

    def apply_amoled_style(self):
        self.setStyleSheet(ui_theme.get_app_qss())

    def init_ui(self):
        central = AmbientBackground(self)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 0, 2, 0)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        lbl_app = QLabel("Яндекс Музыка")
        lbl_app.setFont(ui_theme.font_ui(15, QFont.Weight.DemiBold))
        lbl_app.setStyleSheet(f"color: {ui_theme.TEXT}; font-size: 20px; font-weight: 600;")

        lbl_sub = QLabel("Статус в Discord")
        lbl_sub.setFont(ui_theme.font_ui(10, QFont.Weight.Normal))
        lbl_sub.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
        title_box.addWidget(lbl_app)
        title_box.addWidget(lbl_sub)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        self.discord_badge = DiscordBadge()
        header_layout.addWidget(self.discord_badge)
        main_layout.addLayout(header_layout)

        # Card 1: Track
        self.card_track = QFrame()
        self.card_track.setObjectName("CardTrack")
        self.card_track.setFixedHeight(148)
        track_layout = QHBoxLayout(self.card_track)
        track_layout.setContentsMargins(16, 16, 16, 16)
        track_layout.setSpacing(16)

        self.cover_widget = CoverWidget()
        track_layout.addWidget(self.cover_widget)

        track_meta = QVBoxLayout()
        track_meta.setSpacing(6)
        track_meta.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.track_title = ElidedTitleLabel("Музыка не играет")
        self.track_artist = ElidedArtistLabel("Запустите трек в Яндекс Музыке")


        self.status_line = StatusLine()
        self.status_line.set_state("idle")

        track_meta.addWidget(self.track_title)
        track_meta.addWidget(self.track_artist)
        track_meta.addWidget(self.status_line)
        track_layout.addLayout(track_meta)
        main_layout.addWidget(self.card_track)

        # Card 2: Controls & Switches
        self.card_controls = QFrame()
        self.card_controls.setObjectName("CardControls")
        controls_layout = QVBoxLayout(self.card_controls)
        controls_layout.setContentsMargins(18, 16, 18, 16)
        controls_layout.setSpacing(12)

        # Switch 1: Discord RPC
        rpc_row = QHBoxLayout()
        rpc_info = QVBoxLayout()
        rpc_info.setSpacing(3)
        lbl_rpc_title = ClickableLabel("Показывать трек в Discord")
        lbl_rpc_title.setFont(ui_theme.font_ui(11.5, QFont.Weight.DemiBold))
        lbl_rpc_title.setStyleSheet(f"color: {ui_theme.TEXT}; font-size: 15px; font-weight: 600;")
        lbl_rpc_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_rpc_desc = ClickableLabel("Название и исполнитель в вашем профиле")
        self.lbl_rpc_desc.setFont(ui_theme.font_ui(10, QFont.Weight.Normal))
        self.lbl_rpc_desc.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
        self.lbl_rpc_desc.setCursor(Qt.CursorShape.PointingHandCursor)
        rpc_info.addWidget(lbl_rpc_title)
        rpc_info.addWidget(self.lbl_rpc_desc)
        rpc_row.addLayout(rpc_info)
        rpc_row.addStretch()

        self.switch_rpc = AnimatedToggleSwitch(checked=True, active_color=ui_theme.ACCENT)
        self.switch_rpc.stateChanged.connect(self.on_rpc_toggle)
        lbl_rpc_title.clicked.connect(self.switch_rpc.toggle)
        self.lbl_rpc_desc.clicked.connect(self.switch_rpc.toggle)
        rpc_row.addWidget(self.switch_rpc)
        controls_layout.addLayout(rpc_row)

        # Separator line: 1px LINE
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {ui_theme.LINE}; max-height: 1px;")
        controls_layout.addWidget(sep)

        # Switch 2: Autostart
        auto_row = QHBoxLayout()
        auto_info = QVBoxLayout()
        auto_info.setSpacing(3)
        lbl_auto_title = ClickableLabel("Запускать вместе с Windows")
        lbl_auto_title.setFont(ui_theme.font_ui(11.5, QFont.Weight.DemiBold))
        lbl_auto_title.setStyleSheet(f"color: {ui_theme.TEXT}; font-size: 15px; font-weight: 600;")
        lbl_auto_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_auto_desc = ClickableLabel("Через реестр, раздел Run")
        self.lbl_auto_desc.setFont(ui_theme.font_ui(10, QFont.Weight.Normal))
        self.lbl_auto_desc.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
        self.lbl_auto_desc.setCursor(Qt.CursorShape.PointingHandCursor)
        auto_info.addWidget(lbl_auto_title)
        auto_info.addWidget(self.lbl_auto_desc)
        auto_row.addLayout(auto_info)
        auto_row.addStretch()

        is_auto = is_autostart_enabled()
        self.switch_autostart = AnimatedToggleSwitch(checked=is_auto, active_color=ui_theme.ACCENT)
        self.switch_autostart.stateChanged.connect(self.on_autostart_toggle)
        lbl_auto_title.clicked.connect(self.switch_autostart.toggle)
        self.lbl_auto_desc.clicked.connect(self.switch_autostart.toggle)
        auto_row.addWidget(self.switch_autostart)
        controls_layout.addLayout(auto_row)

        if is_auto:
            self.lbl_auto_desc.setText("Включено, запуск в трее при входе в систему")
            self.lbl_auto_desc.setStyleSheet(f"color: {ui_theme.OK}; font-size: 13px; font-weight: 500;")

        main_layout.addWidget(self.card_controls)

        # Card 3: Region & IP
        self.card_ip = QFrame()
        self.card_ip.setObjectName("CardIP")
        self.card_ip.setProperty("state", "checking")
        ip_layout = QVBoxLayout(self.card_ip)
        ip_layout.setContentsMargins(18, 14, 18, 18)
        ip_layout.setSpacing(8)


        ip_top_row = QHBoxLayout()
        ip_top_row.setSpacing(10)

        self.lbl_ip_icon = QLabel()
        self.lbl_ip_icon.setFixedSize(20, 20)
        self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("globe", 20, ui_theme.DIM))
        ip_top_row.addWidget(self.lbl_ip_icon)

        self.lbl_ip_title = ClickableLabel("Проверяем регион…")
        self.lbl_ip_title.setFont(ui_theme.font_ui(11.5, QFont.Weight.DemiBold))
        self.lbl_ip_title.setStyleSheet(f"color: {ui_theme.TEXT}; font-size: 15px; font-weight: 600;")
        self.lbl_ip_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_ip_title.clicked.connect(self.toggle_ip_reveal)
        ip_top_row.addWidget(self.lbl_ip_title)

        self.lbl_ip_badge = QLabel("••••••••••••••••")
        self.lbl_ip_badge.setFont(ui_theme.font_mono(10.5, QFont.Weight.Normal))
        self.lbl_ip_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lbl_ip_badge.setStyleSheet(
            f"background-color: {ui_theme.SURFACE2}; color: {ui_theme.MUTED}; "
            f"border: 1px solid {ui_theme.LINE}; border-radius: 6px; padding: 3px 8px;"
        )
        self.lbl_ip_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_ip_badge.mouseReleaseEvent = lambda _e: self.toggle_ip_reveal()
        ip_top_row.addWidget(self.lbl_ip_badge)
        ip_top_row.addStretch()

        self.btn_toggle_ip = QPushButton()
        self.btn_toggle_ip.setProperty("class", "icon-btn")
        self.btn_toggle_ip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_toggle_ip.setFixedSize(34, 34)
        self.btn_toggle_ip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_ip.setIcon(ui_theme.svg_icon("eye", 18, ui_theme.MUTED))
        self.btn_toggle_ip.setToolTip("Показать IP")
        self.btn_toggle_ip.clicked.connect(self.toggle_ip_reveal)
        ip_top_row.addWidget(self.btn_toggle_ip)

        self.btn_refresh_ip = QPushButton()
        self.btn_refresh_ip.setProperty("class", "icon-btn")
        self.btn_refresh_ip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_refresh_ip.setFixedSize(34, 34)
        self.btn_refresh_ip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_ip.setIcon(ui_theme.svg_icon("refresh", 18, ui_theme.MUTED))
        self.btn_refresh_ip.setToolTip("Проверить регион")
        self.btn_refresh_ip.clicked.connect(self.check_ip)
        ip_top_row.addWidget(self.btn_refresh_ip)

        ip_layout.addLayout(ip_top_row)

        self.lbl_ip_desc = QLabel("Отправляем запрос к геолокации…")
        self.lbl_ip_desc.setFont(ui_theme.font_ui(10, QFont.Weight.Normal))
        self.lbl_ip_desc.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
        self.lbl_ip_desc.setWordWrap(True)
        ip_layout.addWidget(self.lbl_ip_desc)

        main_layout.addWidget(self.card_ip)

        # Card 4: Collapsible Log
        self.card_log = QFrame()
        self.card_log.setObjectName("CardLog")
        log_card_layout = QVBoxLayout(self.card_log)
        log_card_layout.setContentsMargins(16, 12, 16, 14)
        log_card_layout.setSpacing(10)
        log_card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.btn_toggle_log = QPushButton("Журнал событий")
        self.btn_toggle_log.setProperty("class", "collapse-btn")
        self.btn_toggle_log.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_toggle_log.setFixedHeight(32)
        self.btn_toggle_log.setIcon(ui_theme.svg_icon("chevron-right", 16, ui_theme.MUTED))
        self.btn_toggle_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_log.clicked.connect(self.toggle_log_view)
        log_card_layout.addWidget(self.btn_toggle_log)

        self.log_container = QWidget()
        log_inner_layout = QVBoxLayout(self.log_container)
        log_inner_layout.setContentsMargins(0, 4, 0, 2)
        log_inner_layout.setSpacing(10)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(300)
        self.log_text.setFixedHeight(188)
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pal = self.log_text.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(255, 255, 255, 90))
        self.log_text.setPalette(pal)
        self.log_text.setPlaceholderText("Здесь будут ваши логи^_^")
        log_inner_layout.addWidget(self.log_text)

        log_btn_row = QHBoxLayout()
        log_btn_row.setContentsMargins(0, 0, 0, 0)
        log_btn_row.setSpacing(10)

        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setFont(ui_theme.font_ui(10, QFont.Weight.Medium))
        self.lbl_save_status.setStyleSheet(f"color: {ui_theme.OK}; font-size: 12px; font-weight: 500;")
        self.lbl_save_status.setVisible(False)
        log_btn_row.addWidget(self.lbl_save_status)
        log_btn_row.addStretch()

        self.btn_clear_log = QPushButton("Очистить")
        self.btn_clear_log.setProperty("class", "ghost-btn")
        self.btn_clear_log.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_clear_log.setIcon(ui_theme.svg_icon("trash", 16, ui_theme.MUTED))
        self.btn_clear_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        log_btn_row.addWidget(self.btn_clear_log)

        self.btn_save_log = QPushButton("Сохранить на рабочий стол")
        self.btn_save_log.setProperty("class", "secondary-btn")
        self.btn_save_log.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_save_log.setIcon(ui_theme.svg_icon("save", 16, ui_theme.TEXT))
        self.btn_save_log.setToolTip("Последние 150 строк журнала")
        self.btn_save_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_log.clicked.connect(self.save_logs_desktop)
        log_btn_row.addWidget(self.btn_save_log)

        log_inner_layout.addLayout(log_btn_row)

        LOG_PANEL_H = 240
        self.reveal_panel = RevealPanel(self.log_container, content_height=LOG_PANEL_H)
        log_card_layout.addWidget(self.reveal_panel)

        main_layout.addWidget(self.card_log)

        self.load_initial_logs()

        # Adjust initial compact height based on layout sizeHint
        compact_h = self._get_compact_height()
        self.resize(560, compact_h)

    def set_cover_placeholder(self):
        self._current_displayed_cover_url = None
        if hasattr(self, "cover_widget"):
            self.cover_widget.set_cover_pixmap(None)
        if hasattr(self, "centralWidget") and self.centralWidget():
            self.centralWidget().reset_glow()

    def _get_compact_height(self) -> int:
        if hasattr(self, "lbl_ip_desc"):
            self.lbl_ip_desc.adjustSize()
        if hasattr(self, "card_ip"):
            self.card_ip.adjustSize()

        if hasattr(self, "reveal_panel") and hasattr(self, "card_log"):
            curr_h = self.reveal_panel.height()
            was_vis = self.reveal_panel.isVisible()
            if curr_h > 0 or was_vis:
                self.reveal_panel.setFixedHeight(0)
                self.reveal_panel.setVisible(False)
                self.card_log.updateGeometry()
                self.centralWidget().layout().invalidate()
                self.centralWidget().layout().activate()
                hint_h = self.centralWidget().layout().sizeHint().height()
                self.reveal_panel.setFixedHeight(curr_h)
                self.reveal_panel.setVisible(was_vis)
                self.card_log.updateGeometry()
                self.centralWidget().layout().invalidate()
                self.centralWidget().layout().activate()
                return hint_h

        self.centralWidget().layout().activate()
        hint_h = self.centralWidget().layout().sizeHint().height()
        return hint_h

    def on_track_update(self, title, artist, is_playing, cover_url):
        self.track_title.setText(title)
        self.track_title.setToolTip(title)
        self.track_artist.setText(artist)
        self.track_artist.setToolTip(artist)

        if is_playing:
            self.status_line.set_state("playing")
        else:
            self.status_line.set_state("paused")

        if cover_url and cover_url != self._current_displayed_cover_url:
            self._current_displayed_cover_url = cover_url
            threading.Thread(target=self._load_cover_image, args=(cover_url,), daemon=True).start()
        elif not cover_url:
            self._current_displayed_cover_url = None
            self.cover_widget.set_cover_pixmap(None)
            self.centralWidget().reset_glow()

        self._initial_media_reported = True
        self._check_loading_completion()

    def _load_cover_image(self, url):
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                image = QImage.fromData(r.content)
                self.sig_cover_ready.emit(image, url)
        except Exception:
            pass

    def _on_cover_image_ready(self, image, url):
        if url == self._current_displayed_cover_url and image is not None and not image.isNull():
            pix = QPixmap.fromImage(image)
            dom_color = extract_dominant_accent(image)
            self.cover_widget.set_cover_pixmap(pix, dom_color)
            self.centralWidget().set_glow_color(dom_color, has_cover=True)

    def on_no_track(self):
        self.track_title.setText("Музыка не играет")
        self.track_title.setToolTip("")
        self.track_artist.setText("Запустите трек в Яндекс Музыке")
        self.track_artist.setToolTip("")
        self.status_line.set_state("idle")
        self._current_displayed_cover_url = None
        self.cover_widget.set_cover_pixmap(None)
        self.centralWidget().reset_glow()
        self._initial_media_reported = True
        self._check_loading_completion()

    def on_discord_status(self, connected: bool):
        self.discord_badge.set_status(connected)
        self._initial_discord_reported = True
        self._check_loading_completion()

    def on_rpc_toggle(self, _state):
        enabled = self.switch_rpc.isChecked()
        self.worker.set_rpc_enabled(enabled)
        if enabled:
            self.lbl_rpc_desc.setText("Название и исполнитель в вашем профиле")
            self.lbl_rpc_desc.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
        else:
            self.lbl_rpc_desc.setText("Показ выключен, статус в Discord очищен")
            self.lbl_rpc_desc.setStyleSheet(f"color: {ui_theme.WARN}; font-size: 13px; font-weight: 500;")

    def on_autostart_toggle(self, _state):
        enabled = self.switch_autostart.isChecked()
        success = set_autostart(enabled)
        if success:
            if enabled:
                self.lbl_auto_desc.setText("Включено, запуск в трее при входе в систему")
                self.lbl_auto_desc.setStyleSheet(f"color: {ui_theme.OK}; font-size: 13px; font-weight: 500;")
                self.append_log("Автозапуск активирован в реестре Windows")
            else:
                self.lbl_auto_desc.setText("Через реестр, раздел Run")
                self.lbl_auto_desc.setStyleSheet(f"color: {ui_theme.MUTED}; font-size: 13px; font-weight: 400;")
                self.append_log("Автозапуск отключен")
        else:
            self.switch_autostart.blockSignals(True)
            self.switch_autostart.setChecked(not enabled)
            self.switch_autostart.blockSignals(False)
            self.lbl_auto_desc.setText("Не удалось изменить автозапуск")
            self.lbl_auto_desc.setStyleSheet(f"color: {ui_theme.ERR}; font-size: 13px; font-weight: 500;")

    def check_ip(self):
        if self.ip_thread is not None and self.ip_thread.isRunning():
            return
        self.btn_refresh_ip.setEnabled(False)
        self.card_ip.setProperty("state", "checking")
        self.card_ip.style().unpolish(self.card_ip)
        self.card_ip.style().polish(self.card_ip)
        self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("globe", 20, ui_theme.DIM))
        self.lbl_ip_title.setText("Проверяем регион…")
        self.lbl_ip_desc.setText("Отправляем запрос к геолокации…")
        self.ip_thread = IPCheckerThread()
        self.ip_thread.sig_result.connect(self.on_ip_checked)
        self.ip_thread.start()

    def toggle_ip_reveal(self):
        if self.current_ip:
            self.is_ip_revealed = not self.is_ip_revealed
            self.update_ip_display()

    def update_ip_display(self):
        if not self.current_ip:
            return

        ip_display = self.current_ip if self.is_ip_revealed else "••••••••••••••••"
        self.lbl_ip_badge.setText(ip_display)

        eye_icon = "eye-off" if self.is_ip_revealed else "eye"
        eye_tip = "Скрыть IP" if self.is_ip_revealed else "Показать IP"
        self.btn_toggle_ip.setIcon(ui_theme.svg_icon(eye_icon, 18, ui_theme.MUTED))
        self.btn_toggle_ip.setToolTip(eye_tip)

        if self.is_ru:
            self.card_ip.setProperty("state", "ok")
            self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("check", 20, ui_theme.OK))
            self.lbl_ip_title.setText("Россия")
            self.lbl_ip_desc.setText("Раздельное туннелирование работает, обложки загружаются.")
        elif self.current_country:
            self.card_ip.setProperty("state", "warn")
            self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("alert-triangle", 20, ui_theme.ERR))
            self.lbl_ip_title.setText(self.current_country)
            self.lbl_ip_desc.setText("Яндекс блокирует обложки из-за границы (ошибка 451). Выключите VPN или добавьте программу в раздельное туннелирование.")
        else:
            self.card_ip.setProperty("state", "unknown")
            self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("globe", 20, ui_theme.DIM))
            self.lbl_ip_title.setText("Неизвестный регион")
            self.lbl_ip_desc.setText("Не удалось определить страну.")

        self.card_ip.style().unpolish(self.card_ip)
        self.card_ip.style().polish(self.card_ip)
        if not self._is_log_expanded:
            self.resize(560, self._get_compact_height())

    def on_ip_checked(self, ip, country, is_ru):
        self.btn_refresh_ip.setEnabled(True)
        self.current_ip = ip
        self.current_country = country
        self.is_ru = is_ru
        if ip:
            self.update_ip_display()
        else:
            self.card_ip.setProperty("state", "unknown")
            self.card_ip.style().unpolish(self.card_ip)
            self.card_ip.style().polish(self.card_ip)
            self.lbl_ip_icon.setPixmap(ui_theme.svg_pixmap("globe", 20, ui_theme.DIM))
            self.lbl_ip_title.setText("Не удалось определить IP")
            self.lbl_ip_desc.setText("Проверьте интернет-соединение и нажмите «Проверить».")
            self.lbl_ip_badge.setText("—")
            if not self._is_log_expanded:
                self.resize(560, self._get_compact_height())
        self._check_loading_completion()

    def toggle_log_view(self):
        if self._log_anim.is_running():
            self._log_anim.stop()

        self._is_log_expanded = not self._is_log_expanded
        LOG_PANEL_H = 240

        if self._is_log_expanded:
            self.btn_toggle_log.setIcon(ui_theme.svg_icon("chevron-down", 16, ui_theme.ACCENT))
            self.reveal_panel.setVisible(True)

            base_h = self._get_compact_height()
            spacing = self.card_log.layout().spacing() if hasattr(self, "card_log") and self.card_log.layout() else 10
            target_win_h = base_h + LOG_PANEL_H + spacing

            # 1. Instantly resize the window to target height (strictly once upfront)
            if self.height() < target_win_h:
                self.resize(560, target_win_h)
                screen = self.screen()
                if screen:
                    avail = screen.availableGeometry()
                    fg = self.frameGeometry()
                    if fg.bottom() > avail.bottom():
                        overflow = fg.bottom() - avail.bottom()
                        self.move(self.x(), max(avail.top(), self.y() - overflow))

            start_log_h = self.reveal_panel.height()
            target_log_h = LOG_PANEL_H

            def on_step(progress, val):
                self.reveal_panel.set_reveal_height(int(val))

            def on_finished():
                self.reveal_panel.set_reveal_height(target_log_h)
                scrollbar = self.log_text.verticalScrollBar()
                if scrollbar:
                    scrollbar.setValue(scrollbar.maximum())

            self._log_anim.start(start_log_h, target_log_h, on_step, on_finished)
        else:
            self.btn_toggle_log.setIcon(ui_theme.svg_icon("chevron-right", 16, ui_theme.MUTED))
            start_log_h = self.reveal_panel.height()
            target_log_h = 0

            def on_step(progress, val):
                self.reveal_panel.set_reveal_height(int(val))

            def on_finished():
                self.reveal_panel.setVisible(False)
                self.reveal_panel.set_reveal_height(0)
                self.card_log.updateGeometry()
                self.centralWidget().layout().invalidate()
                self.centralWidget().layout().activate()
                self.centralWidget().updateGeometry()
                self.updateGeometry()
                target_win_h = self._get_compact_height()
                self.resize(560, target_win_h)

            self._log_anim.start(start_log_h, target_log_h, on_step, on_finished)

    def append_log(self, text):
        stamp = time.strftime("%H:%M:%S")
        safe_text = html.escape(text)

        if "Трек:" in text:
            color = ui_theme.ACCENT
        elif any(k in text.lower() for k in ("ошибк", "failed", "отключен", "error")):
            color = ui_theme.ERR
        elif any(k in text.lower() for k in ("успешно", "подключен", "активирован")):
            color = ui_theme.OK
        elif any(k in text.lower() for k in ("обложк", "фоне", "запуск")):
            color = ui_theme.DIM
        else:
            color = ui_theme.MUTED

        entry_html = (
            f'<div style="margin: 2px 0; line-height: 1.3;">'
            f'<span style="color: {ui_theme.DIM}; font-family: \'{ui_theme.MONO_FONT_FAMILY}\';">[{stamp}]</span> '
            f'<span style="color: {color}; font-family: \'{ui_theme.MONO_FONT_FAMILY}\';">{safe_text}</span>'
            f'</div>'
        )
        self.log_text.appendHtml(entry_html)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def load_initial_logs(self):
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-25:]
                    for l in lines:
                        line_str = l.strip()
                        if line_str:
                            if len(line_str) >= 19 and line_str[4] == '-' and line_str[7] == '-':
                                stamp = line_str[11:19]
                                rest = html.escape(line_str[20:])
                                if "track:" in rest.lower():
                                    color = ui_theme.ACCENT
                                elif "failed" in rest.lower() or "error" in rest.lower():
                                    color = ui_theme.ERR
                                elif "connected" in rest.lower():
                                    color = ui_theme.OK
                                else:
                                    color = ui_theme.MUTED
                                entry_html = (
                                    f'<div style="margin: 2px 0; line-height: 1.3;">'
                                    f'<span style="color: {ui_theme.DIM}; font-family: \'{ui_theme.MONO_FONT_FAMILY}\';">[{stamp}]</span> '
                                    f'<span style="color: {color}; font-family: \'{ui_theme.MONO_FONT_FAMILY}\';">{rest}</span>'
                                    f'</div>'
                                )
                                self.log_text.appendHtml(entry_html)
                            else:
                                self.log_text.appendPlainText(line_str)
            except Exception:
                pass

    def save_logs_desktop(self):
        try:
            desktop = get_real_desktop_path()
            out_file = os.path.join(desktop, "ymusic_rpc_logs.txt")
            lines = []
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            recent = lines[-150:] if lines else ["(Логов пока нет)\n"]
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(f"=== YMusic Discord RPC Logs (Последние {len(recent)} строк) ===\n")
                f.write(f"=== Время экспорта: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                f.writelines(recent)
            self.lbl_save_status.setText(f"Сохранено на рабочий стол: {os.path.basename(out_file)}")
            self.lbl_save_status.setStyleSheet(f"color: {ui_theme.OK}; font-size: 12px; font-weight: 500;")
            self.lbl_save_status.setVisible(True)
            QTimer.singleShot(4000, lambda: self.lbl_save_status.setVisible(False))
        except Exception as e:
            self.lbl_save_status.setText(f"Не удалось сохранить: {e}")
            self.lbl_save_status.setStyleSheet(f"color: {ui_theme.ERR}; font-size: 12px; font-weight: 500;")
            self.lbl_save_status.setVisible(True)
            QTimer.singleShot(5000, lambda: self.lbl_save_status.setVisible(False))

    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setToolTip("YMusic Discord RPC")
        icon_path = os.path.join(APP_DIR, "app_icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(APP_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))

        from PyQt6.QtWidgets import QMenu
        tray_menu = QMenu()
        action_show = tray_menu.addAction("Показать окно")
        action_show.triggered.connect(self.show_and_activate)

        action_toggle_rpc = tray_menu.addAction("Вкл / Выкл RPC")
        action_toggle_rpc.triggered.connect(lambda: self.switch_rpc.setChecked(not self.switch_rpc.isChecked()))

        tray_menu.addSeparator()
        action_quit = tray_menu.addAction("Выход")
        action_quit.triggered.connect(self.close_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_and_activate()

    def show_and_activate(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "loading_overlay") and self.loading_overlay and self.loading_overlay.isVisible():
            self.loading_overlay.setGeometry(self.centralWidget().rect())

    def _check_loading_completion(self):
        if getattr(self, "_initial_load_complete", False):
            return
        if self._initial_discord_reported and self._initial_media_reported:
            self._on_component_ready()

    def _on_component_ready(self):
        if getattr(self, "_initial_load_complete", False):
            return
        now = time.time()
        elapsed_ms = (now - getattr(self, "_loading_start_time", now)) * 1000.0
        # If at least 1100ms has elapsed (1 full rhythmic breathing pulse), dismiss now
        if elapsed_ms >= 1100:
            self._try_dismiss_loading()
        else:
            # Wait for remainder of the 1100ms cycle for calm consistent pacing
            remain_ms = max(50, int(1100 - elapsed_ms))
            QTimer.singleShot(remain_ms, self._try_dismiss_loading)

    def _try_dismiss_loading(self):
        if getattr(self, "_initial_load_complete", False):
            return
        self._initial_load_complete = True
        if hasattr(self, "loading_overlay") and self.loading_overlay:
            self.loading_overlay.dismiss()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                self.hide()
        super().changeEvent(event)

    def closeEvent(self, event):
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            self.close_app()

    def close_app(self):
        if hasattr(self, "_local_server") and self._local_server:
            try:
                self._local_server.close()
                QLocalServer.removeServer(LOCAL_SERVER_NAME)
            except Exception:
                pass
        if hasattr(self, "worker"):
            self.worker.stop()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        QApplication.quit()


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ymusic.discord.rpc")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("YMusic Discord RPC")

    # Initialize typography (Onest & JetBrains Mono)
    ui_theme.init_fonts()

    # 1. Single-Instance Check via QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer(LOCAL_SERVER_NAME)
    if socket.waitForConnected(600):
        socket.write(b"SHOW")
        socket.waitForBytesWritten(600)
        socket.disconnectFromServer()
        sys.exit(0)

    # 2. sole instance: initialize local IPC server for single-instance control
    QLocalServer.removeServer(LOCAL_SERVER_NAME)
    local_server = QLocalServer()
    local_server.listen(LOCAL_SERVER_NAME)

    start_minimized = "--minimized" in sys.argv

    window = MainWindow(start_minimized=start_minimized)
    window._local_server = local_server

    def handle_ipc_connection():
        client = local_server.nextPendingConnection()
        if client:
            if client.waitForReadyRead(600):
                msg = client.readAll().data()
                if b"SHOW" in msg:
                    window.show_and_activate()
            client.disconnectFromServer()

    local_server.newConnection.connect(handle_ipc_connection)

    if not start_minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

