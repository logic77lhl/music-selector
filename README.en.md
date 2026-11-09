[中文](README.md) | **English**

# Music Selector — audition and pick from a local music library

A **fully local** tool (no Flask, no cloud) for going through thousands of tracks quickly and exporting a playlist.

Backend is Python's standard-library `http.server`; front end is plain HTML/CSS/JS with no framework.

---

## Features

- Scan a directory and recursively index audio files (mp3/flac/wav/m4a/aac/ogg, etc.)
- Compute a "chorus candidate start" for each track so auditioning jumps to the good part
- Three-column layout: track list / player / shortlist
- Search by title, artist, album, filename, relative path
- Filter: all / unselected / selected
- **Audition mode**: play N seconds (5–60, default 20) then advance automatically
- One-click add / remove from the shortlist
- Export `.m3u` (absolute paths, UTF-8, works in mainstream players)
- Full keyboard shortcuts
- Shortlist persists across restarts

---

## Requirements

- Windows / macOS / Linux
- Python 3.8+ (with pip)

---

## Install

```bash
cd music-selector
pip install -r requirements.txt
```

> The only required dependency is `mutagen` (reads audio metadata).

**Optional but strongly recommended — real chorus detection:**

```bash
pip install pychorus librosa numpy
```

Re-run indexing afterwards (`analyze_music.py`, or "change folder" in the UI) to detect choruses for the whole library (multiprocess; ~17 minutes for 2,779 tracks). Without it the tool falls back to a 35% start point.

---

## Usage

### 0. One-click start (Windows)

Double-click **`启动.bat`** in the project root. It checks Python and dependencies (installing `mutagen` on first run), prompts for a music folder if no index exists, starts the local server, and opens the browser.

> Once an index exists, double-clicking `启动.bat` goes straight to the UI.

### 1. Build the library index

```bash
python analyze_music.py "path/to/your/music"
```

The script walks the directory, reads metadata, computes chorus candidates, and writes `data/library.json` (UTF-8). Re-runs reuse the cache: already-analysed tracks are skipped, only new files are processed.

### 2. Start the web app

```bash
python app.py
```

It opens **http://localhost:5000** automatically.

### 3. The interface

| Area | What it does |
|---|---|
| Left | Track list with search and filters; click to play |
| Middle | Player controls, progress, volume, audition toggle |
| Right | Shortlist; click to jump, × to remove |

**Audition mode**: when enabled, each track plays for the configured number of seconds and then advances. Drag the slider to change it (5–60 s).

### 4. Shortcuts

| Key | Action |
|---|---|
| `Space` | play / pause |
| `↑` | previous track |
| `↓` | next track |
| `A` | add current track to shortlist |
| `D` | remove current track from shortlist |
| `F` | focus search |
| `Esc` | leave search |

> Shortcuts are suppressed while you type in the search box.

### 5. Export

Click "Export M3U" (top right). The browser downloads `playlist.m3u` and a copy is saved to `data/playlist.m3u`. Paths are absolute, so foobar2000, MusicBee, and VLC can import it directly.

---

## Layout

```
music-selector/
├── 启动.bat             # one-click launcher (Windows)
├── analyze_music.py     # scan the library, produce library.json
├── app.py               # web server (stdlib http.server, no Flask)
├── templates/
│   └── index.html       # single-file front end (CSS/JS inline)
├── data/                # generated
│   ├── library.json     # library index
│   ├── selected.json    # shortlist (relative paths)
│   ├── config.json      # current music folder
│   └── playlist.m3u     # exported playlist
├── TECHNICAL.md          # architecture, API, data formats, failure handling
├── requirements.txt
└── README.md
```

---

## How the chorus start is chosen

`analyze_music.py` tries, in order:

1. **pychorus** — chromagram features plus a time-lag similarity matrix; finds the most repeated chorus section.
2. **Fallback** — 35% into the track.

> Measured on a 2,779-track library with pychorus installed: **82% land on the real chorus**, ~17 minutes total across processes.

**Making it fast:**

- **Multiprocessing** — one worker per CPU core (`CHORUS_WORKERS` at the top of `analyze_music.py`).
- **Only the first 80%** — choruses almost never sit at the very end, so decoding is cut short.
- **Cached upgrades** — each record carries a `chorus_source` flag (`pychorus` / `fallback`); rescans reuse pychorus hits and only retry fallbacks.

The front end re-validates on play: an invalid or out-of-range `chorus_start` falls back to 0.

---

## Changing the music folder

**In the UI (recommended)**: click "Change folder", paste a path, and the scan starts with a live progress bar; the list refreshes when it finishes.

**From the command line**:

```bash
python analyze_music.py "D:\new\music"
```

This rewrites `data/library.json` (cached tracks are reused). The shortlist stores **relative paths**, so it survives as long as the file layout doesn't change.

---

## FAQ

**"Failed to load" in the page**
Make sure `data/library.json` exists (`analyze_music.py`) and `app.py` is running.

**No sound when clicking a track**
Check the file still exists on disk. Some browsers can't decode `.wma`; convert to mp3/flac.

**Chorus start is off**
Install the pychorus trio, then rescan (or delete `data/library.json` and re-run `analyze_music.py`).

**Detection is slow**
It already parallelises and only analyses the first 80%. Tune `CHORUS_WORKERS` and `ANALYZE_MAX_RATIO` at the top of `analyze_music.py`. Results are cached with `chorus_source`, so later scans only retry fallbacks.

**Thousands of tracks load slowly**
The first analysis reads metadata for every file (usually 1–3 minutes); afterwards it's incremental. The page loads the whole index at once — 3,000–5,000 tracks is fine in a modern browser.

**Absolute paths changed after moving machines**
Re-run `python analyze_music.py "new/path"`. The shortlist uses relative paths and is unaffected.

**Port 5000 is taken**
Change `PORT = 5000` at the top of `app.py`.

---

## Notes

- Everything stays local; nothing is uploaded.
- The shortlist lives in `data/selected.json` — don't hand-edit its format.
- Exported `.m3u` files are UTF-8 with absolute paths.
- Playback uses HTML5 Audio; format support depends on the browser (Chrome/Edge handle mp3/flac/m4a/ogg well).

## License

[MIT](LICENSE)
