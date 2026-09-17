# Music Selector 技术文档

本工具是一个**纯本地运行**的「音乐快速试听与选歌」应用，后端使用 Python 标准库 `http.server`，前端使用原生 HTML/CSS/JS，仅依赖 `mutagen` 读取音频元数据，无需 Flask，不依赖任何云服务。

---

## 1. 总体架构

```
┌────────────────────────────────────────────────────────────┐
│                        浏览器 (Web UI)                       │
│   index.html  (原生 HTML + CSS + JS，无框架)                  │
│   · 歌曲列表 / 播放器 / 已选列表 三栏布局                       │
│   · Audio API 播放 · 试听模式 · 快捷键 · 目录切换弹窗            │
└───────────────▲─────────────────────────────▲───────────────┘
                │ HTTP/JSON (REST)            │ 静态页面
┌───────────────┴─────────────────────────────┴───────────────┐
│                     app.py (Web 服务)                        │
│   Python 标准库 http.server (ThreadingHTTPServer)            │
│   · API 路由  · Range 音频流  · 后台扫描线程  · 数据持久化       │
└───────────────▲──────────────────────────────────────────────┘
                │ 函数调用 (import analyze_music)
┌───────────────┴──────────────────────────────────────────────┐
│                     analyze_music.py (索引器)                  │
│   · 递归扫描目录  · mutagen 读元数据  · 副歌候选检测/兜底        │
└───────────────┬──────────────────────────────────────────────┘
                │ 读写
┌───────────────▼──────────────────────────────────────────────┐
│   data/  library.json · selected.json · config.json · playlist.m3u │
└──────────────────────────────────────────────────────────────┘
```

**数据流**：`analyze_music.py` 将音乐目录扫描成 `library.json` 索引 → `app.py` 读取索引并通过 HTTP 提供查询/流媒体/选歌 API → 前端渲染并播放。

---

## 2. 技术选型与理由

| 技术 | 选择 | 理由 |
|------|------|------|
| Web 服务 | Python `http.server.ThreadingHTTPServer` | 标准库，零依赖，天然支持多线程处理并发请求 |
| 元数据读取 | `mutagen` | 轻量、纯 Python，支持 mp3/flac/wav/m4a/aac/ogg/wma/opus |
| 副歌检测 | `pychorus`（可选）+ 兜底策略 | pychorus 不可用时不阻塞，自动降级为时长 35% 起播 |
| 前端 | 原生 HTML/CSS/JS | 无框架、单文件、加载快，几千条列表用事件委托 + `content-visibility` 保证流畅 |
| 音频流 | 浏览器 HTML5 `<audio>` + HTTP Range | 支持拖动进度条、快速 seek，无需下载完整文件 |
| 数据文件 | JSON (UTF-8) | 人类可读、便于调试、可靠持久化 |

> 不采用 Flask/FastAPI：任务仅需少量路由，标准库足以胜任，降低部署复杂度与依赖风险。

---

## 3. 模块划分

### 3.1 analyze_music.py — 索引生成器

核心函数：

- `read_metadata(filepath)` — 用 mutagen 读取 `title/artist/album/duration`；任何异常回退到「文件名 / Unknown / 0」，绝不中断扫描。
- `detect_chorus_start(filepath, duration)` — 副歌候选起点：
  1. 若安装了 `pychorus`，用 `find_chorus` 检测；
  2. 否则/失败时**兜底**为 `duration * 0.35`（流行歌副歌多在此区间）。
- `scan_music_directory(music_dir, progress_cb=None)` — 主流程，返回 `(library, stats)`：
  - 递归 `os.walk` 收集音频文件；
  - **增量缓存**：`library.json` 中的条目按 `relative_path + 绝对路径` 双重匹配，命中则直接复用（新加绝对路径比对，避免换目录后误用旧路径）；
  - `progress_cb` 回调每文件进度，供 Web 端实时显示。

`sys.exit` 已被移除，目录无效时抛 `ValueError`，保证可被 app.py 安全导入调用。

### 3.2 app.py — Web 服务

- **数据层**：`load/save` 系列函数统一管理 `library.json`、`selected.json`、`config.json`、`playlist.m3u`，全部 UTF-8。
- **MusicHandler**（`BaseHTTPRequestHandler` 子类）：
  - `_send_json` / `_send_bytes` — 统一 JSON/二进制响应；
  - `_send_file` — 通用文件发送，支持 HTTP Range（206 分段响应）；
  - 路由分发在 `do_GET`（`POST` 复用同一路由逻辑）。
- **后台扫描**：`/api/rescan` 校验参数后立即返回，真正扫描放在 `threading.Thread` 中执行，前端通过 `/api/scan_status` 轮询进度，避免阻塞页面。

### 3.3 templates/index.html — 前端

单文件页面，逻辑分区：

- **状态**：`library`（全量）、`filteredSongs`（当前过滤结果）、`selectedPaths`（Set，已选相对路径）、`curIdx`（当前歌曲在过滤列表中的下标）。
- **渲染**：`filterAndRender()` 统一处理筛选 + 搜索 + 保持当前播放项；列表用 `content-visibility:auto` 虚拟化，几千行不卡。
- **试听模式**：`startAudition()` 在 `audio.play` 事件中启动（修复了切歌后计时失效的问题），到点 `playNext()` 自动切歌；暂停时 `clearAudition()` 取消。
- **起播跳转**：`playAt()` 监听 `loadedmetadata`，将 `currentTime` 设置为 `chorus_start`（越界自动回退 0）。

---

## 4. 数据文件格式

### 4.1 data/library.json
```json
[
  {
    "id": 0,
    "title": "歌名",
    "artist": "歌手",
    "album": "专辑",
    "filename": "song.flac",
    "path": "D:\\Music\\song.flac",
    "relative_path": "song.flac",
    "duration": 240.5,
    "chorus_start": 84.2,
    "chorus_source": "pychorus"
  }
]
```
`id` 即数组下标，`path` 为绝对路径（流媒体用），`relative_path` 为已选状态的主键。`chorus_source` 标记副歌来源（`pychorus`=真实检测，`fallback`=35% 兜底），供增量扫描判断是否需要重测升级。

### 4.2 data/selected.json
```json
["albums\\a.flac", "albums\\b.flac"]
```
相对路径列表。因基于相对路径，换机器/换根目录不丢失已选。

### 4.3 data/config.json
```json
{ "dir": "D:\\Music" }
```
记录最近一次扫描的音乐目录，供前端「换目录」弹窗预填与展示。

### 4.4 data/playlist.m3u
```m3u
#EXTM3U
#EXTINF:240,歌手 - 歌名
D:\Music\song.flac
```
标准 M3U 格式，绝对路径，UTF-8 编码。

---

## 5. HTTP API 接口

| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/` `/index.html` | 前端页面 | text/html（`Cache-Control: no-store`） |
| GET | `/api/library` | 全量歌曲（含 `selected` 标记） | `[{...}]` |
| GET | `/api/stream/{id}` | 音频流，支持 Range | 200 / 206 分段 / 404 |
| POST | `/api/select/{id}` | 加入已选 | `{"status":"ok","count":n}` |
| POST | `/api/deselect/{id}` | 移除已选 | `{"status":"ok","count":n}` |
| GET | `/api/export` | 下载并保存 `playlist.m3u` | 文件（`Content-Disposition: attachment`） |
| GET | `/api/config` | 当前音乐目录 | `{"dir":"..."}` |
| POST | `/api/rescan` | 提交新目录，后台扫描 | `{"status":"started","dir":"..."}` 或 400/409 |
| GET | `/api/scan_status` | 扫描进度/结果 | `{running,progress,total,done,error,stats}` |
| HEAD | `/api/stream/{id}` | 音频元信息 | headers（浏览器预检用） |

**错误约定**：统一返回 JSON `{"error":"描述"}`，状态码 400（参数错误）/ 404（不存在）/ 409（扫描中）/ 500（内部错误）。

---

## 6. 音频流媒体与 Range 支持

浏览器 `<audio>` 对进度条 seek 依赖 HTTP Range。`_send_file` 的实现要点：

1. 解析 `Range: bytes=start-end`（支持 `bytes=start-` 开区间）；
2. 非法范围返回 `416 + Content-Range: bytes */size`；
3. 合法范围返回 `206`，带 `Content-Range: bytes s-e/total` 与 `Content-Length`；
4. 分块读取（64KB）写入，`BrokenPipeError`/`ConnectionResetError` 静默处理（用户拖动进度时会中断旧请求）。

这使得用户在本地网络下拖动进度条几乎无延迟，且无需把整个文件传给浏览器。

---

## 7. 副歌候选策略（三级降级 + 并行加速）

```
pychorus（已安装）  ──►  兜底: duration * 35%
```

**检测原理**（pychorus）：
1. `librosa.load` 解码音频（sr=22050，只取前 `ANALYZE_MAX_RATIO`=80% 时长，加速解码）；
2. STFT（n_fft=16384）→ chroma_stft 得到 12 维色度特征 `chroma`；
3. 构建 **Time-Time 相似度矩阵** 与 **Time-Lag 相似度矩阵**；
4. 去噪后检测对角线方向上的重复线（`detect_lines`），代表重复片段；
5. `count_overlapping_lines` 统计互相覆盖的重复段，得分最高的线即副歌；
6. 返回副歌起点秒数。

**加速机制**：
- **多进程并行**：`ProcessPoolExecutor` 按 `CHORUS_WORKERS or os.cpu_count()-1` 并行检测，2779 首约 17 分钟（单线程需 2 小时）；
- **时长截断**：只分析前 80%（副歌几乎不出现在末尾）；
- **增量缓存升级**：每条记录含 `chorus_source`（`pychorus`/`fallback`），第二次扫描时 pychorus 命中的直接复用，仅重测兜底歌曲（尝试升级）。

**降级路径**：pychorus 未装 / 检测失败 / 结果越界（≤5s 或 ≥时长-5s）→ 35% 兜底。

- 前端起播时二次校验：`chorus_start` 为 null / 负数 / 超出 `duration-1` 时回退到 0。
- 检测失败绝不阻塞：系统始终可用，只是从 0 或兜底位置播放。

**实测**（2779 首）：82% 命中真实副歌（2286 首），18% 兜底。

---

## 8. 并发与线程模型

- `ThreadingHTTPServer`：每个请求一个线程，音频流传输与 UI 查询互不阻塞。
- `_LOCK`：保护 `selected.json` 的并发读写（加选/移除）。
- 扫描线程：`/api/rescan` 启动 `daemon` 线程，共享全局 `_SCAN` 字典作为进度状态；前端 500ms 轮询。
- 浏览器侧每个请求可并发拉取 Range 分片。

---

## 9. 容错与健壮性设计

| 场景 | 处理 |
|------|------|
| 目录不存在 / 无音频文件 | `analyze_music.py` 抛 `ValueError`，API 返回 400 提示 |
| 元数据缺失 / 损坏 | `read_metadata` 兜底默认值，不中断扫描 |
| 副歌检测失败 | 降级为 35% 起播 |
| 音频文件被移动/删除 | `/api/stream` 返回 404 `{"error":"file missing"}` |
| `library.json` 不存在 | 服务仍启动，前端提示先扫描 |
| 文件格式不被浏览器支持 | 播放触发 `error` 事件，自动跳到下一首并 toast 提示 |
| selected.json 损坏 | 解析失败返回空集合，不崩溃 |
| 浏览器缓存旧页面 | `index.html` 响应 `Cache-Control: no-store` |
| 端口占用 | 修改 `app.py` 顶部 `PORT` 即可 |

---

## 10. 性能设计

- **扫描**：首次 2779 首约 80s（纯读元数据，无重采样）；增量扫描全缓存命中 <1s。
- **列表渲染**：`content-visibility:auto` 让浏览器只渲染视口附近的行；`contain-intrinsic-size` 提供占位尺寸。
- **事件**：列表/已选用事件委托（`closest`），搜索用 120ms 防抖。
- **数据量**：3000~5000 首的 `library.json` 约 1MB，浏览器一次性加载无压力。

---

## 11. 一键启动（Windows）

双击项目根目录下的 **`启动.bat`**：

1. 自动检查 Python 是否可用；
2. 首次运行自动安装 `mutagen`；
3. 若尚无 `library.json`，交互式提示输入音乐目录并生成索引；
4. 启动 Web 服务并自动打开浏览器。

已生成过索引后，以后启动只需双击，直接进页面。

---

## 12. 扩展点与改进方向

- **更准的副歌检测**：安装 `pychorus` + `librosa` + `numpy`，重启 `analyze_music.py`（删除 `library.json` 可强制全量重扫）。
- **封面图**：用 mutagen 读 embedded cover，经 `/api/cover/{id}` 提供给前端。
- **播放列表增删改**：`selected.json` 已是 JSON，可扩展排序/分组字段。
- **更多格式**：`AUDIO_EXTENSIONS` 与 `AUDIO_MIME` 两个字典扩展即可。
- **端口/主机配置**：`HOST`/`PORT` 常量化，可加启动参数。
- **导入导出兼容**：导出时可将 `relative_path` 一并写入 m3u 注释，便于回导。

---

## 13. 常用命令速查

```bash
python analyze_music.py "D:\Music"   # 手动生成/更新索引
python app.py                        # 启动服务（自动开浏览器）
```

或直接双击 `启动.bat` 完成上述两件事。