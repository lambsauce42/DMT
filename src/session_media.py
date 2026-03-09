from __future__ import annotations

import mimetypes
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover - exercised only when QtMultimedia is unavailable
    QAudioOutput = None
    QMediaPlayer = None


SUPPORTED_MEDIA_EXTENSIONS: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}
EFFECT_POOL_SIZE = 4


def validate_media_source_path(path: str) -> tuple[bool, str]:
    candidate = Path(str(path or "").strip())
    if not candidate.exists() or not candidate.is_file():
        return False, "Media file not found."
    suffix = candidate.suffix.lower()
    if suffix == ".wav":
        return False, "WAV is not supported for streamed session media. Use a compressed format."
    if suffix not in SUPPORTED_MEDIA_EXTENSIONS:
        return (
            False,
            "Unsupported media format. Use MP3, OGG, M4A, AAC, or FLAC.",
        )
    return True, ""


def media_content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    explicit = SUPPORTED_MEDIA_EXTENSIONS.get(suffix)
    if explicit:
        return explicit
    guessed, _encoding = mimetypes.guess_type(str(path))
    return str(guessed or "application/octet-stream")


@dataclass(slots=True)
class MediaAssetRecord:
    asset_id: str
    path: Path
    title: str
    kind: str


class _MediaThreadingHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, request_handler_class, media_server):
        super().__init__(server_address, request_handler_class)
        self.media_server = media_server


class _MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "DMTMedia/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        message = format % args if args else format
        self.server.media_server._log(f"[INFO] Media server: {message}")

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(include_body=False)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(include_body=True)

    def _serve(self, *, include_body: bool) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        token = str(query.get("token", [""])[0] or "")
        if token != self.server.media_server.token:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid media token")
            return

        parts = [segment for segment in parsed.path.split("/") if segment]
        if len(parts) != 2 or parts[0] not in {"music", "effect"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown media path")
            return
        asset_id = parts[1]
        record = self.server.media_server.asset(asset_id)
        if record is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown media asset")
            return
        if not record.path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Media file missing")
            return

        try:
            file_size = int(record.path.stat().st_size)
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to stat media file")
            return

        start = 0
        end = max(0, file_size - 1)
        status = HTTPStatus.OK
        range_header = str(self.headers.get("Range") or "").strip()
        if range_header.startswith("bytes="):
            requested = range_header[len("bytes=") :].strip()
            start_text, _, end_text = requested.partition("-")
            try:
                if start_text:
                    start = max(0, int(start_text))
                if end_text:
                    end = min(end, int(end_text))
                if start > end or start >= file_size:
                    raise ValueError("invalid range")
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return

        length = (end - start) + 1
        self.send_response(status)
        self.send_header("Content-Type", media_content_type_for_path(record.path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if not include_body:
            return

        with record.path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


class SessionMediaHttpServer:
    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self._log = log or (lambda _line: None)
        self._assets: dict[str, MediaAssetRecord] = {}
        self._token = uuid.uuid4().hex
        self._server: _MediaThreadingHttpServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        if self._server is None:
            return 0
        return int(self._server.server_port or 0)

    def start(self) -> tuple[bool, str]:
        if self._server is not None:
            return True, ""
        try:
            self._server = _MediaThreadingHttpServer(("0.0.0.0", 0), _MediaRequestHandler, self)
        except OSError as exc:
            self._server = None
            return False, str(exc)
        self._thread = threading.Thread(target=self._server.serve_forever, name="DMTMediaServer", daemon=True)
        self._thread.start()
        self._log(f"[INFO] Media stream listening on 0.0.0.0:{self.port}")
        return True, ""

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            self._thread = None

    def register_asset(self, *, asset_id: str, title: str, kind: str, path: str) -> tuple[bool, str]:
        ok, message = validate_media_source_path(path)
        if not ok:
            return False, message
        candidate = Path(path)
        self._assets[str(asset_id)] = MediaAssetRecord(
            asset_id=str(asset_id),
            path=candidate,
            title=str(title or candidate.stem or asset_id),
            kind=str(kind or "music"),
        )
        return True, ""

    def unregister_missing_assets(self, valid_asset_ids: set[str]) -> None:
        wanted = {str(asset_id) for asset_id in valid_asset_ids}
        stale = [asset_id for asset_id in self._assets.keys() if asset_id not in wanted]
        for asset_id in stale:
            self._assets.pop(asset_id, None)

    def asset(self, asset_id: str) -> MediaAssetRecord | None:
        return self._assets.get(str(asset_id))

    def build_asset_url(self, *, host: str, asset_id: str, kind: str) -> str:
        safe_kind = "effect" if str(kind or "").strip().lower() == "effect" else "music"
        return f"http://{host}:{self.port}/{safe_kind}/{urllib.parse.quote(str(asset_id))}?token={self.token}"


class SessionMediaPlaybackEngine(QObject):
    musicPositionChanged = Signal(int, int)
    musicPlaybackStateChanged = Signal(str)
    musicError = Signal(str)
    effectCacheReady = Signal(str, str)
    effectCacheFailed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._music_mix_volume = 100
        self._effects_mix_volume = 100
        self._personal_music_volume = 100
        self._personal_effects_volume = 100
        self._mute_music = False
        self._mute_effects = False
        self._music_loop = False
        self._active_music_source = ""
        self._music_source_ready = False
        self._pending_music_position_ms: int | None = None
        self._pending_music_action = ""
        self._duration_ms = 0
        self._pending_effect_downloads: dict[str, bool] = {}
        self._pending_effect_plays: set[str] = set()
        self._effect_cache_paths: dict[str, str] = {}
        self._effect_download_threads: dict[str, threading.Thread] = {}
        self._media_available_error = ""

        self._music_player = None
        self._music_output = None
        self._warm_player = None
        self._warm_output = None
        self._effect_players: list[tuple[object, object]] = []
        self._effect_cursor = 0

        if QAudioOutput is None or QMediaPlayer is None:
            self._media_available_error = "Qt multimedia playback is unavailable in this environment."
            return

        self._music_output = QAudioOutput(self)
        self._music_player = QMediaPlayer(self)
        self._music_player.setAudioOutput(self._music_output)
        self._music_player.positionChanged.connect(self._on_music_position_changed)
        self._music_player.durationChanged.connect(self._on_music_duration_changed)
        self._music_player.playbackStateChanged.connect(self._on_music_playback_state_changed)
        self._music_player.mediaStatusChanged.connect(self._on_music_media_status_changed)
        self._music_player.errorOccurred.connect(self._on_music_error)

        self._warm_output = QAudioOutput(self)
        self._warm_player = QMediaPlayer(self)
        self._warm_player.setAudioOutput(self._warm_output)
        self._warm_output.setVolume(0.0)

        for _index in range(EFFECT_POOL_SIZE):
            output = QAudioOutput(self)
            player = QMediaPlayer(self)
            player.setAudioOutput(output)
            player.errorOccurred.connect(self._on_effect_error)
            self._effect_players.append((player, output))

        self._apply_music_volume()
        self._apply_effects_volume()

    @property
    def available(self) -> bool:
        return not self._media_available_error

    @property
    def availability_error(self) -> str:
        return str(self._media_available_error or "")

    @property
    def current_music_position_ms(self) -> int:
        if self._music_player is None:
            return 0
        return int(self._music_player.position() or 0)

    @property
    def current_music_duration_ms(self) -> int:
        if self._music_player is None:
            return int(self._duration_ms or 0)
        duration = int(self._music_player.duration() or 0)
        return max(duration, int(self._duration_ms or 0))

    @property
    def current_music_state(self) -> str:
        if self._music_player is None:
            return "stopped"
        state_value = self._music_player.playbackState()
        state_name = getattr(state_value, "name", str(state_value))
        if "Playing" in state_name:
            return "playing"
        if "Paused" in state_name:
            return "paused"
        return "stopped"

    @property
    def active_music_source(self) -> str:
        return str(self._active_music_source or "")

    def set_mix_levels(self, *, music_mix: int | None = None, effects_mix: int | None = None) -> None:
        if music_mix is not None:
            self._music_mix_volume = max(0, min(100, int(music_mix)))
        if effects_mix is not None:
            self._effects_mix_volume = max(0, min(100, int(effects_mix)))
        self._apply_music_volume()
        self._apply_effects_volume()

    def set_personal_preferences(
        self,
        *,
        music_volume: int | None = None,
        effects_volume: int | None = None,
        mute_music: bool | None = None,
        mute_effects: bool | None = None,
    ) -> None:
        if music_volume is not None:
            self._personal_music_volume = max(0, min(100, int(music_volume)))
        if effects_volume is not None:
            self._personal_effects_volume = max(0, min(100, int(effects_volume)))
        if mute_music is not None:
            self._mute_music = bool(mute_music)
        if mute_effects is not None:
            self._mute_effects = bool(mute_effects)
        self._apply_music_volume()
        self._apply_effects_volume()

    def stop_all(self) -> None:
        self.stop_music()
        self.stop_all_effects()

    def warm_music(self, source: str) -> None:
        if not self.available or self._warm_player is None:
            if self._media_available_error:
                self.musicError.emit(self._media_available_error)
            return
        self._warm_player.setSource(_source_to_qurl(source))

    def set_music_loop(self, loop: bool) -> None:
        self._music_loop = bool(loop)

    def play_music(self, source: str, *, position_ms: int = 0, paused: bool = False, loop: bool = False) -> None:
        if not self.available or self._music_player is None:
            if self._media_available_error:
                self.musicError.emit(self._media_available_error)
            return
        self._music_loop = bool(loop)
        next_source = str(source or "")
        if next_source and next_source != self._active_music_source:
            self._music_source_ready = False
            self._pending_music_position_ms = max(0, int(position_ms))
            self._pending_music_action = "pause" if paused else "play"
            self._music_player.setSource(_source_to_qurl(next_source))
            self._active_music_source = next_source
            return
        if not self._music_source_ready:
            self._pending_music_position_ms = max(0, int(position_ms))
            self._pending_music_action = "pause" if paused else "play"
            return
        if position_ms >= 0:
            self._music_player.setPosition(int(position_ms))
        if paused:
            self._music_player.pause()
        else:
            self._music_player.play()

    def pause_music(self) -> None:
        if self._music_player is not None:
            self._music_player.pause()

    def stop_music(self) -> None:
        if self._music_player is not None:
            self._pending_music_position_ms = None
            self._pending_music_action = ""
            self._music_source_ready = False
            self._music_player.stop()

    def seek_music(self, position_ms: int) -> None:
        if self._music_player is not None:
            if not self._music_source_ready:
                self._pending_music_position_ms = max(0, int(position_ms))
                return
            self._music_player.setPosition(max(0, int(position_ms)))

    def play_effect(self, *, cache_key: str, source: str) -> None:
        if not self.available:
            if self._media_available_error:
                self.effectCacheFailed.emit(cache_key, self._media_available_error)
            return
        player, _output = self._next_effect_player()
        player.setSource(_source_to_qurl(source))
        player.play()

    def stop_all_effects(self) -> None:
        for player, _output in self._effect_players:
            player.stop()

    def ensure_effect_cached(
        self,
        *,
        cache_key: str,
        source_url: str,
        target_path: str,
        play_when_ready: bool = False,
    ) -> str:
        target = Path(target_path)
        if target.exists():
            self._effect_cache_paths[cache_key] = str(target)
            if play_when_ready:
                self.play_effect(cache_key=cache_key, source=str(target))
            return str(target)
        if play_when_ready:
            self._pending_effect_plays.add(cache_key)
        if self._pending_effect_downloads.get(cache_key):
            return str(target)
        self._pending_effect_downloads[cache_key] = True
        thread = threading.Thread(
            target=self._download_effect_asset,
            args=(cache_key, str(source_url), str(target)),
            name=f"DMTMediaEffect-{cache_key[:8]}",
            daemon=True,
        )
        self._effect_download_threads[cache_key] = thread
        thread.start()
        return str(target)

    def _download_effect_asset(self, cache_key: str, source_url: str, target_path: str) -> None:
        try:
            target = Path(target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_path = target.with_suffix(f"{target.suffix}.part")
            with urllib.request.urlopen(source_url, timeout=20) as response, temp_path.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            os.replace(temp_path, target)
            self._effect_cache_paths[cache_key] = str(target)
            self.effectCacheReady.emit(cache_key, str(target))
            if cache_key in self._pending_effect_plays:
                self._pending_effect_plays.discard(cache_key)
                QTimer.singleShot(0, lambda key=cache_key, path=str(target): self.play_effect(cache_key=key, source=path))
        except Exception as exc:
            self.effectCacheFailed.emit(cache_key, str(exc))
        finally:
            self._pending_effect_downloads.pop(cache_key, None)
            self._effect_download_threads.pop(cache_key, None)

    def _next_effect_player(self):
        if not self._effect_players:
            raise RuntimeError("Effect playback pool is unavailable.")
        start = self._effect_cursor
        count = len(self._effect_players)
        for offset in range(count):
            index = (start + offset) % count
            player, output = self._effect_players[index]
            state_name = getattr(player.playbackState(), "name", "")
            if "Playing" not in str(state_name):
                self._effect_cursor = (index + 1) % count
                return player, output
        player, output = self._effect_players[self._effect_cursor]
        self._effect_cursor = (self._effect_cursor + 1) % count
        player.stop()
        return player, output

    def _apply_music_volume(self) -> None:
        if self._music_output is None:
            return
        final_value = 0 if self._mute_music else (self._music_mix_volume * self._personal_music_volume) / 10000.0
        self._music_output.setVolume(max(0.0, min(1.0, final_value)))

    def _apply_effects_volume(self) -> None:
        final_value = 0 if self._mute_effects else (self._effects_mix_volume * self._personal_effects_volume) / 10000.0
        bounded = max(0.0, min(1.0, final_value))
        for _player, output in self._effect_players:
            output.setVolume(bounded)

    def _on_music_position_changed(self, position_ms: int) -> None:
        self.musicPositionChanged.emit(int(position_ms), self.current_music_duration_ms)

    def _on_music_duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.musicPositionChanged.emit(self.current_music_position_ms, self.current_music_duration_ms)

    def _on_music_playback_state_changed(self, _state) -> None:
        self.musicPlaybackStateChanged.emit(self.current_music_state)

    def _on_music_media_status_changed(self, status) -> None:
        status_name = getattr(status, "name", str(status))
        if self._music_player is None:
            return
        lowered = str(status_name)
        if "NoMedia" in lowered or "InvalidMedia" in lowered or "LoadingMedia" in lowered:
            self._music_source_ready = False
        if "LoadedMedia" in lowered or "BufferedMedia" in lowered:
            self._music_source_ready = True
            pending_position = self._pending_music_position_ms
            pending_action = self._pending_music_action
            self._pending_music_position_ms = None
            self._pending_music_action = ""
            if pending_position is not None and pending_position > 0:
                self._music_player.setPosition(int(pending_position))
            if pending_action == "pause":
                self._music_player.pause()
            elif pending_action == "play":
                self._music_player.play()
        if "EndOfMedia" in str(status_name) and self._music_loop:
            self._music_player.setPosition(0)
            self._music_player.play()

    def _on_music_error(self, _error, error_string: str) -> None:
        message = str(error_string or "").strip() or "Unable to play music."
        self.musicError.emit(message)

    def _on_effect_error(self, _error, error_string: str) -> None:
        message = str(error_string or "").strip() or "Unable to play effect."
        self.effectCacheFailed.emit("", message)


def _source_to_qurl(source: str) -> QUrl:
    clean_source = str(source or "").strip()
    parsed = urllib.parse.urlparse(clean_source)
    if parsed.scheme in {"http", "https"}:
        return QUrl(clean_source)
    return QUrl.fromLocalFile(clean_source)
