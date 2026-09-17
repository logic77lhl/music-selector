#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_music.py - 扫描本地音乐目录并生成 library.json 索引。

用法:
    python analyze_music.py "D:\\Music"
    python analyze_music.py "C:\\Users\\hailo\\Music"

说明:
    - 递归扫描目录中的 mp3/flac/wav/m4a/aac/ogg 等音频文件
    - 使用 mutagen 读取元数据（标题/歌手/专辑/时长）
    - 检测"副歌候选起点" chorus_start：
        1) 若安装了 pychorus，使用它检测
        2) 否则使用兜底策略：歌曲时长的 35% 位置（流行歌副歌大多在这附近）
    - 结果保存为 data/library.json（UTF-8）
    - 再次运行会复用缓存（已分析过的歌曲不重复检测），快速增量更新
"""

import os
import sys
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LIBRARY_FILE = DATA_DIR / "library.json"

# 支持的音频扩展名
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma", ".opus"}

# 兜底起播位置（歌曲时长的百分比）
FALLBACK_RATIO = 0.35

# 副歌检测并行进程数（None = 自动按 CPU 核数）
CHORUS_WORKERS = None

# pychorus 分析时只加载歌曲前 80%（副歌几乎不会出现在末尾，可显著提速）
ANALYZE_MAX_RATIO = 0.8

# 副歌最小/最大 clip 长度
CHORUS_CLIP_LENGTH = 15


def read_metadata(filepath: Path) -> dict:
    """使用 mutagen 读取音频文件元数据，任何失败都回退到默认值。"""
    title = filepath.stem
    artist = "Unknown"
    album = "Unknown"
    duration = 0.0

    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(filepath), easy=True)
        if audio is not None:
            if getattr(audio, "info", None) is not None:
                length = getattr(audio.info, "length", None)
                if length:
                    duration = float(length)
            tags = getattr(audio, "tags", None)
            if tags:
                title = str(tags.get("title")[0]) if tags.get("title") else title
                artist = str(tags.get("artist")[0]) if tags.get("artist") else artist
                album = str(tags.get("album")[0]) if tags.get("album") else album
    except Exception as e:
        print(f"  [WARN] 元数据读取失败: {filepath.name} ({e})")

    return {
        "title": title or filepath.stem,
        "artist": artist or "Unknown",
        "album": album or "Unknown",
        "duration": round(duration, 2),
    }


def detect_chorus_start(filepath: Path, duration: float) -> tuple:
    """
    检测副歌候选起点（秒）。
    返回 (chorus_start, source)，source 为 "pychorus" 或 "fallback"。
    优先 pychorus；不可用或失败时，使用兜底策略（时长 35%）。
    兜底策略保证不总是从歌曲开头试听，且不会阻塞整体功能。
    """
    fallback = round(duration * FALLBACK_RATIO, 2) if duration > 0 else 0.0
    if duration <= 0:
        return 0.0, "fallback"

    # ---- 可选：pychorus 副歌检测 ----
    try:
        import librosa
        import numpy as np
        from pychorus.helpers import find_chorus
        from pychorus.constants import N_FFT

        # 与 pychorus.create_chroma 保持一致，但只加载前 ANALYZE_MAX_RATIO 时长
        if ANALYZE_MAX_RATIO > 0:
            limit = max(10.0, duration * ANALYZE_MAX_RATIO)
            y, sr = librosa.load(str(filepath), sr=22050, mono=True, duration=limit)
            song_length_sec = y.shape[0] / float(sr)
            if song_length_sec <= 0:
                return fallback, "fallback"
            S = np.abs(librosa.stft(y, n_fft=N_FFT)) ** 2
            chroma = librosa.feature.chroma_stft(S=S, sr=sr)
            result = find_chorus(chroma, sr, song_length_sec, CHORUS_CLIP_LENGTH)
        else:
            from pychorus.helpers import create_chroma

            chroma, _y, _sr, song_length_sec = create_chroma(str(filepath))
            result = find_chorus(chroma, _sr, song_length_sec, CHORUS_CLIP_LENGTH)

        if result is not None and isinstance(result, (int, float)):
            result = float(result)
            if 5.0 < result < duration - 5.0:
                return round(result, 2), "pychorus"
    except ImportError:
        pass  # pychorus/librosa 未安装，直接走兜底
    except Exception:
        pass  # 检测失败，直接走兜底

    # ---- 兜底策略：歌曲时长的 35% 位置 ----
    return fallback, "fallback"


def scan_music_directory(music_dir: str, progress_cb=None):
    """扫描目录并生成 library.json。返回 (library, stats)。

    - 新文件：多进程并行做 pychorus 副歌检测
    - 已缓存且来源为 pychorus：直接复用（不再分析）
    - 已缓存但来源为 fallback：重新检测，尝试升级为 pychorus
    """
    music_dir = Path(music_dir).resolve()
    if not music_dir.is_dir():
        raise ValueError(f"目录不存在或不是目录: {music_dir}")

    DATA_DIR.mkdir(exist_ok=True)

    # 读取已有缓存（相对路径 -> 歌曲条目）
    cached = {}
    if LIBRARY_FILE.exists():
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                for song in json.load(f):
                    if isinstance(song, dict):
                        cached[song.get("relative_path", "")] = song
        except Exception:
            pass

    # 递归收集音频文件
    print(f"扫描目录: {music_dir}")
    audio_files = []
    for root, _dirs, files in os.walk(music_dir, followlinks=True):
        for fname in sorted(files):
            fpath = Path(root) / fname
            if fpath.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(fpath)

    total = len(audio_files)
    print(f"找到 {total} 个音频文件")
    if total == 0:
        raise ValueError("未找到音频文件，请检查目录路径。")

    t0 = time.time()

    # 分类：直接复用 / 需要检测
    reuse = {}      # index -> entry（pychorus 来源的缓存直接复用）
    to_detect = []  # (index, fpath, duration, rel_path)

    for i, fpath in enumerate(audio_files):
        try:
            rel_path = str(fpath.relative_to(music_dir))
        except ValueError:
            rel_path = str(fpath)

        abs_path = str(fpath.resolve())
        cached_entry = cached.get(rel_path)

        if cached_entry and cached_entry.get("path") == abs_path:
            if cached_entry.get("chorus_source") == "pychorus":
                entry = dict(cached_entry)
                entry["id"] = i
                reuse[i] = entry
                continue
            # fallback 来源：复用其元数据，但重测副歌
            meta = cached_entry
        else:
            meta = read_metadata(fpath)

        to_detect.append((i, fpath, meta.get("duration", 0.0), rel_path))

    # 并行检测副歌
    detected = {}  # index -> (chorus_start, source)
    if to_detect:
        n = len(to_detect)
        workers = CHORUS_WORKERS or max(1, (os.cpu_count() or 2) - 1)
        print(f"需要检测副歌: {n} 首 (并行 {min(workers, n)} 进程)...")
        if progress_cb is not None:
            progress_cb(0, total, to_detect[0][1])

        if len(to_detect) >= 2 and workers > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed

            with ProcessPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(detect_chorus_start, Path(fpath), duration): (i, fpath)
                    for (i, fpath, duration, rel_path) in to_detect
                }
                for done, fut in enumerate(as_completed(future_map), start=1):
                    i, fpath = future_map[fut]
                    try:
                        chorus_start, source = fut.result()
                    except Exception:
                        chorus_start, source = _safe_fallback(fpath, to_detect, i)
                    detected[i] = (chorus_start, source)
                    if progress_cb is not None:
                        progress_cb(done, total, fpath)
        else:
            for idx, (i, fpath, duration, rel_path) in enumerate(to_detect):
                try:
                    chorus_start, source = detect_chorus_start(fpath, duration)
                except Exception:
                    chorus_start, source = _safe_fallback(fpath, to_detect, i)
                detected[i] = (chorus_start, source)
                if progress_cb is not None:
                    progress_cb(idx + 1, total, fpath)

    # 合并构建最终索引
    library = []
    for i, fpath in enumerate(audio_files):
        if i in reuse:
            library.append(reuse[i])
            continue
        try:
            rel_path = str(fpath.relative_to(music_dir))
        except ValueError:
            rel_path = str(fpath)

        meta = read_metadata(fpath)
        chorus_start, source = detected.get(i, (0.0, "fallback"))

        library.append({
            "id": i,
            "title": meta["title"],
            "artist": meta["artist"],
            "album": meta["album"],
            "filename": fpath.name,
            "path": str(fpath.resolve()),
            "relative_path": rel_path,
            "duration": meta["duration"],
            "chorus_start": chorus_start,
            "chorus_source": source,
        })

    # 保存索引
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    pychorus_count = sum(1 for s in library if s.get("chorus_source") == "pychorus")
    stats = {
        "dir": str(music_dir),
        "total": len(library),
        "cached": len(reuse),
        "new": len(detected),
        "pychorus": pychorus_count,
        "fallback": len(library) - pychorus_count,
        "elapsed": round(elapsed, 1),
    }
    print(f"\n索引生成完成! 歌曲总数: {stats['total']} 缓存复用: {stats['cached']} 本次检测: {stats['new']} "
          f"副歌命中: {stats['pychorus']} 兜底: {stats['fallback']} 耗时: {elapsed:.1f}s")
    if progress_cb is not None:
        progress_cb(total, total, None)
    return library, stats


def _safe_fallback(fpath, to_detect, index):
    """并行 worker 异常时的安全兜底。"""
    for (i, _fp, duration, _rp) in to_detect:
        if i == index:
            fb = round(duration * FALLBACK_RATIO, 2) if duration > 0 else 0.0
            return fb, "fallback"
    return 0.0, "fallback"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze_music.py <音乐目录路径>")
        print("示例: python analyze_music.py \"D:\\Music\"")
        sys.exit(1)

    try:
        library, stats = scan_music_directory(sys.argv[1])
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)