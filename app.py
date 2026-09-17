#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py - 本地音乐快速试听与选歌工具 Web 服务（零依赖，无需 Flask）。

用法:
    python app.py

访问:
    http://localhost:5000

说明:
    - 使用 Python 标准库 http.server，无需安装任何 Web 框架
    - 音频流支持 HTTP Range 请求（浏览器可拖动进度条 / 快速跳转）
    - 已选数据保存在 data/selected.json，重启后保留
    - 导出 data/playlist.m3u（绝对路径，UTF-8）
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LIBRARY_FILE = DATA_DIR / "library.json"
SELECTED_FILE = DATA_DIR / "selected.json"
PLAYLIST_FILE = DATA_DIR / "playlist.m3u"
CONFIG_FILE = DATA_DIR / "config.json"
TEMPLATE_DIR = BASE_DIR / "templates"

import analyze_music

HOST = "127.0.0.1"
PORT = 5000

CHUNK_SIZE = 64 * 1024

AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".wma": "audio/x-ms-wma",
    ".opus": "audio/opus",
}

_LOCK = threading.Lock()

# 后台扫描状态
_SCAN = {
    "running": False,
    "progress": 0,
    "total": 0,
    "done": False,
    "error": None,
    "stats": None,
}


# ───────────────────────── 数据层 ─────────────────────────

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_library():
    if LIBRARY_FILE.exists():
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def load_selected_paths():
    if SELECTED_FILE.exists():
        try:
            with open(SELECTED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(str(p) for p in data)
        except Exception:
            pass
    return set()


def save_selected_paths(paths):
    DATA_DIR.mkdir(exist_ok=True)
    with open(SELECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(paths), f, ensure_ascii=False, indent=2)


def export_playlist():
    """将已选歌曲导出为 data/playlist.m3u，返回字节内容或 None。"""
    library = load_library()
    selected = load_selected_paths()
    DATA_DIR.mkdir(exist_ok=True)

    lines = ["#EXTM3U"]
    for song in library:
        rel = song.get("relative_path", "")
        if rel in selected:
            dur = int(song.get("duration", 0) or 0)
            artist = song.get("artist", "Unknown")
            title = song.get("title", "Unknown")
            lines.append(f"#EXTINF:{dur},{artist} - {title}")
            lines.append(song.get("path", ""))

    content = "\n".join(lines) + "\n"
    try:
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[ERROR] 导出 m3u 失败: {e}")
        return None
    return content.encode("utf-8")


# ───────────────────────── HTTP 处理器 ─────────────────────────

class MusicHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- 工具方法 ----

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, filepath: Path, content_type=None):
        """发送本地文件，支持 Range 请求。"""
        if content_type is None:
            import mimetypes

            content_type, _ = mimetypes.guess_type(str(filepath))
        content_type = content_type or "application/octet-stream"

        try:
            file_size = filepath.stat().st_size
        except OSError:
            self._send_json({"error": "file missing"}, status=404)
            return

        range_header = self.headers.get("Range")

        if range_header:
            m = self._parse_range(range_header, file_size)
            if m is None:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */{}".format(file_size))
                self.end_headers()
                return
            start, end = m
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, file_size))
            self.send_header("Content-Length", str(length))
            self.end_headers()
            try:
                with open(filepath, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
            except OSError:
                pass
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except OSError:
            pass

    @staticmethod
    def _parse_range(range_header, file_size):
        try:
            if not range_header.startswith("bytes="):
                return None
            parts = range_header[len("bytes="):].split("-", 1)
            start_str = parts[0].strip()
            end_str = parts[1].strip() if len(parts) > 1 else ""

            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            if start >= file_size:
                return None
            end = min(end, file_size - 1)
            if end < start:
                return None
            return start, end
        except (ValueError, IndexError):
            return None

    def _get_song(self, song_id):
        library = load_library()
        try:
            idx = int(song_id)
        except (ValueError, TypeError):
            return None
        if idx < 0 or idx >= len(library):
            return None
        return library[idx]

    # ---- 路由 ----

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        try:
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path == "/api/library":
                self._api_library()
            elif path == "/api/export":
                self._api_export()
            elif path == "/api/config":
                self._api_config()
            elif path == "/api/rescan":
                self._api_rescan()
            elif path == "/api/scan_status":
                self._api_scan_status()
            elif path.startswith("/api/stream/"):
                self._api_stream(path[len("/api/stream/"):])
            elif path.startswith("/api/select/"):
                self._api_select(path[len("/api/select/"):])
            elif path.startswith("/api/deselect/"):
                self._api_deselect(path[len("/api/deselect/"):])
            else:
                self._send_json({"error": "not found"}, status=404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("[ERROR] {} -> {}".format(path, e))
            try:
                self._send_json({"error": str(e)}, status=500)
            except Exception:
                pass

    def do_POST(self):
        self.do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/stream/"):
            song = self._get_song(path[len("/api/stream/"):])
            if song is None:
                self._send_json({"error": "not found"}, status=404)
                return
            fp = Path(song.get("path", ""))
            if not fp.exists():
                self._send_json({"error": "file missing"}, status=404)
                return
            content_type = AUDIO_MIME.get(fp.suffix.lower(), "application/octet-stream")
            try:
                size = fp.stat().st_size
            except OSError:
                size = 0
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self.end_headers()
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, fmt, *args):
        pass  # 关闭默认访问日志，保持终端干净

    # ---- API 实现 ----

    def _serve_index(self):
        index_path = TEMPLATE_DIR / "index.html"
        if index_path.exists():
            import mimetypes

            _, enc = mimetypes.guess_type("index.html")
            content_type = "text/html; charset=utf-8" if enc else "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(index_path.stat().st_size))
            self.end_headers()
            try:
                with open(index_path, "rb") as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        else:
            self._send_json({"error": "index.html missing"}, status=500)

    def _api_library(self):
        library = load_library()
        selected = load_selected_paths()
        result = []
        for song in library:
            s = dict(song)
            s["selected"] = song.get("relative_path", "") in selected
            result.append(s)
        self._send_json(result)

    def _api_stream(self, song_id):
        song = self._get_song(song_id)
        if song is None:
            self._send_json({"error": "not found"}, status=404)
            return
        fp = Path(song.get("path", ""))
        if not fp.exists():
            self._send_json({"error": "file missing", "path": song.get("path", "")}, status=404)
            return
        content_type = AUDIO_MIME.get(fp.suffix.lower(), "application/octet-stream")
        self._send_file(fp, content_type)

    def _api_select(self, song_id):
        song = self._get_song(song_id)
        if song is None:
            self._send_json({"error": "invalid id"}, status=400)
            return
        with _LOCK:
            selected = load_selected_paths()
            selected.add(song.get("relative_path", ""))
            save_selected_paths(selected)
        self._send_json({"status": "ok", "count": len(selected)})

    def _api_deselect(self, song_id):
        song = self._get_song(song_id)
        if song is None:
            self._send_json({"error": "invalid id"}, status=400)
            return
        with _LOCK:
            selected = load_selected_paths()
            selected.discard(song.get("relative_path", ""))
            save_selected_paths(selected)
        self._send_json({"status": "ok", "count": len(selected)})

    def _api_export(self):
        content = export_playlist()
        if content is None:
            self._send_json({"error": "export failed"}, status=500)
            return
        self._send_bytes(
            content,
            "audio/x-mpegurl; charset=utf-8",
            extra_headers={"Content-Disposition": 'attachment; filename="playlist.m3u"'},
        )

    def _api_config(self):
        cfg = load_config()
        if not cfg.get("dir") and LIBRARY_FILE.exists():
            cfg["dir"] = "未知（由命令行生成）"
        self._send_json(cfg)

    def _api_rescan(self):
        global _SCAN
        if _SCAN["running"]:
            self._send_json({"error": "正在扫描中，请稍候"}, status=409)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if 0 < length < (1 << 20) else b""
        except Exception:
            raw = b""

        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}

        music_dir = str(body.get("dir", "")).strip().strip('"')
        if not music_dir:
            self._send_json({"error": "请提供音乐目录路径"}, status=400)
            return

        target = Path(music_dir)
        if not target.exists() or not target.is_dir():
            self._send_json({"error": f"目录不存在: {music_dir}"}, status=400)
            return

        _SCAN = {
            "running": True,
            "progress": 0,
            "total": 0,
            "done": False,
            "error": None,
            "stats": None,
        }

        def worker():
            global _SCAN
            try:
                library, stats = analyze_music.scan_music_directory(
                    str(target), progress_cb=on_progress
                )
                save_config({"dir": str(target.resolve())})
                _SCAN.update({"done": True, "stats": stats, "total": stats["total"]})
            except Exception as e:
                _SCAN.update({"done": True, "error": str(e)})
            finally:
                _SCAN["running"] = False

        def on_progress(i, total, fpath):
            _SCAN["progress"] = i
            _SCAN["total"] = total

        threading.Thread(target=worker, daemon=True).start()
        self._send_json({"status": "started", "dir": str(target.resolve())})

    def _api_scan_status(self):
        self._send_json(_SCAN)


# ───────────────────────── 启动 ─────────────────────────

def open_browser():
    """尝试自动打开浏览器（失败则忽略）。"""
    import time

    time.sleep(1.0)
    try:
        webbrowser.open("http://{}:{}".format(HOST, PORT))
    except Exception:
        pass


def main():
    DATA_DIR.mkdir(exist_ok=True)

    if not LIBRARY_FILE.exists():
        print("警告: data/library.json 不存在，请先运行:")
        print("   python analyze_music.py \"你的音乐目录\"")
        print()

    print("=" * 52)
    print("  Music Selector - 本地音乐快速试听与选歌工具")
    print("=" * 52)
    print("  访问地址  http://{}:{}".format(HOST, PORT))
    print("  音乐库    {}".format(LIBRARY_FILE))
    print("  已选数据  {}".format(SELECTED_FILE))
    print("  Ctrl+C 退出")
    print("=" * 52)

    server = ThreadingHTTPServer((HOST, PORT), MusicHandler)
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
        server.server_close()


if __name__ == "__main__":
    main()