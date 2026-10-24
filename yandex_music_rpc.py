import asyncio
import os
import sys
import threading
import time

import requests
from pypresence import Presence
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
)

CLIENT_ID = "1536782293438435491"
POLL_INTERVAL_SECONDS = 2
DISCORD_RECONNECT_INTERVAL_SECONDS = 5
TARGET_APP_ID_HINT = "yandex"
PLAYBACK_STATUS_PLAYING = 4
YANDEX_LARGE_TEXT = "Яндекс Музыка"

LOG_PATH = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
    "log.txt",
)


def log(message):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def fetch_cover_url(title, artist):
    try:
        query = f"{artist} {title}".strip()
        resp = requests.get(
            "https://api.music.yandex.net/search",
            params={"text": query, "type": "track", "page": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=3,
        )
        resp.raise_for_status()
        data = resp.json()
        tracks = data.get("result", {}).get("tracks", {}).get("results", [])
        if tracks:
            cover_uri = tracks[0].get("coverUri")
            if cover_uri:
                url = cover_uri.replace("%%", "600x600")
                if not url.startswith("http"):
                    url = "https://" + url
                return url
    except Exception as e:
        log(f"Cover fetch failed: {e}")
    return None


class CoverArtCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self.cover_url = None

    def start_new_track(self, title, artist):
        with self._lock:
            self._version += 1
            version = self._version
            self.cover_url = None
        threading.Thread(
            target=self._fetch, args=(title, artist, version), daemon=True
        ).start()

    def _fetch(self, title, artist, version):
        url = fetch_cover_url(title, artist)
        with self._lock:
            if version == self._version:
                self.cover_url = url


async def get_active_track():
    manager = await MediaManager.request_async()
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

        candidate = Presence(self.client_id)
        try:
            candidate.connect()
        except Exception as e:
            log(f"Discord connect attempt failed: {e}")
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
            log(f"Discord update failed, connection lost: {e}")
            self._reset()
            return False

    def clear(self):
        if not self.connected or self.rpc is None:
            return False
        try:
            self.rpc.clear()
            return True
        except Exception as e:
            log(f"Discord clear failed, connection lost: {e}")
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


def main():
    discord = DiscordRPCManager(CLIENT_ID, DISCORD_RECONNECT_INTERVAL_SECONDS)
    cover_cache = CoverArtCache()

    print("Подключаюсь к Discord...")
    log("Script started")

    if discord.try_connect(force=True):
        print("Discord подключен.")
        log("Discord connected")
    else:
        print("Discord не найден. Буду искать его в фоне.")
        log("Discord not available at startup, will keep retrying")

    print("Слежу за Яндекс.Музыкой...")

    loop = asyncio.new_event_loop()

    last_track = None
    last_is_playing = None
    last_sent_cover_url = None
    start_timestamp = None
    need_presence_resend = False

    try:
        while True:
            was_connected = discord.connected
            if not discord.connected:
                discord.try_connect()
            if discord.connected and not was_connected:
                print("Discord обнаружен. Переподключение...")
                print("Discord подключен.")
                log("Discord (re)connected")
                need_presence_resend = True

            track = poll_yandex_track(loop)

            if track is None:
                if last_track is not None:
                    was_connected_before = discord.connected
                    cleared = discord.clear()
                    last_track = None
                    last_is_playing = None
                    last_sent_cover_url = None
                    if cleared:
                        print("Ничего не играет — статус очищен.")
                        log("Presence cleared (no active track)")
                    elif was_connected_before and not discord.connected:
                        print("Discord соединение потеряно.")
                        print("Ожидание Discord...")
                        log("Discord connection lost while clearing presence")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            title, artist, is_playing = track
            current_track = (title, artist)
            track_changed = current_track != last_track
            play_state_changed = is_playing != last_is_playing

            if track_changed:
                start_timestamp = int(time.time())
                last_sent_cover_url = None
                cover_cache.start_new_track(title, artist)
                print(f"[yandex] Сейчас играет: {artist} — {title}")
                log(f"Yandex track changed: {artist} - {title}")

            cover_url = cover_cache.cover_url
            cover_just_arrived = (
                cover_url is not None and cover_url != last_sent_cover_url
            )

            if track_changed or play_state_changed or need_presence_resend or cover_just_arrived:
                image_kwargs = {"large_image": cover_url} if cover_url else {}
                was_connected_before_update = discord.connected

                if is_playing:
                    ok = discord.update(
                        details=title,
                        state=artist or YANDEX_LARGE_TEXT,
                        large_text=YANDEX_LARGE_TEXT,
                        start=start_timestamp,
                        **image_kwargs,
                    )
                else:
                    ok = discord.update(
                        details=title,
                        state=f"{artist} (на паузе)" if artist else "На паузе",
                        large_text=YANDEX_LARGE_TEXT,
                        **image_kwargs,
                    )

                if ok:
                    need_presence_resend = False
                    last_sent_cover_url = cover_url
                elif was_connected_before_update and not discord.connected:
                    print("Discord соединение потеряно.")
                    print("Ожидание Discord...")
                    log("Discord connection lost while updating presence")

            last_track = current_track
            last_is_playing = is_playing

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("Останавливаюсь...")
        log("Shutting down (Ctrl+C)")
    finally:
        discord.shutdown()
        loop.close()
        log("Script stopped")


if __name__ == "__main__":
    main()